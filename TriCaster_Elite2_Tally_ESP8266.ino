#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266HTTPUpdateServer.h>
#include <DNSServer.h>
#include <WiFiUdp.h>
#include <EEPROM.h>

// =====================================================
// TRICASTER ELITE 2 WIFI TALLY - ESP8266
// Modifier uniquement ce numéro avant le premier flash.
// Exemple public : 1 = 192.168.1.81, 2 = .82, ... 8 = .88
// =====================================================
#define DEFAULT_TALLY_NUMBER 3
#define FIRMWARE_VERSION "4.1.1"

// Valeurs utilisees au premier flash / apres reset usine.
// Elles peuvent ensuite etre modifiees sans reflasher via le portail SETUP
// ou depuis le Tally Manager.
const char* DEFAULT_WIFI_SSID = "YOUR_WIFI_SSID";
const char* DEFAULT_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEFAULT_ADMIN_TOKEN = "CHANGE_ME";

#define PIN_GREEN D1
#define PIN_RED   D2
#define PIN_BLUE  D3
#define LED_ON LOW
#define LED_OFF HIGH

const uint32_t LEGACY_CONFIG_MAGIC = 0xCA12AC06;
const uint32_t CONFIG_MAGIC = 0xCA12AC08;
const unsigned long POLL_INTERVAL = 250;
const unsigned long TALLY_TIMEOUT = 2000;
const unsigned long HEARTBEAT_INTERVAL = 1000;
const unsigned long IDENTIFY_DURATION = 5000;

// Roaming Wi-Fi entre plusieurs points d'acces utilisant le meme SSID.
// Le scan ne se lance que si le signal devient faible afin de ne pas
// perturber inutilement le polling tally.
const int ROAM_RSSI_TRIGGER = -70;               // dBm : commencer a chercher un meilleur AP
const int ROAM_MIN_GAIN = 8;                     // dB  : gain minimum avant de basculer
const unsigned long ROAM_SCAN_INTERVAL = 10000; // ms  : intervalle entre deux verifications
const unsigned long ROAM_COOLDOWN = 15000;      // ms  : evite les bascules aller/retour
const unsigned long ROAM_CONNECT_TIMEOUT = 8000;// ms  : abandon d'une tentative de roaming

// Reconnexion apres une vraie perte Wi-Fi.
// Bleu fixe = recherche du SSID.
// Bleu clignotant = SSID trouve, association Wi-Fi en cours.
const unsigned long WIFI_CONNECT_TIMEOUT = 8000;
const unsigned long WIFI_SCAN_RETRY = 1000;
const unsigned long BLUE_BLINK_INTERVAL = 250;

// Si aucun Wi-Fi configure n'est joignable au demarrage, le portail
// TALLY-XX-SETUP est active automatiquement apres ce delai.
const unsigned long STARTUP_SETUP_TIMEOUT = 30000;
const byte DNS_PORT = 53;

struct LegacyConfigV3 {
  uint32_t magic;
  char name[32];
  uint8_t ip[4];
  uint8_t tricaster[4];
  uint8_t camera;
  uint8_t pgmR, pgmG, pgmB;
  uint8_t prevR, prevG, prevB;
  uint8_t brightness;
};

struct Config {
  uint32_t magic;

  char name[32];
  char ssid[33];
  char wifiPassword[65];
  char adminToken[33];

  bool dhcp;
  uint8_t ip[4];
  uint8_t gateway[4];
  uint8_t subnet[4];
  uint8_t dns[4];

  uint8_t tricaster[4];
  uint8_t camera;

  uint8_t pgmR, pgmG, pgmB;
  uint8_t prevR, prevG, prevB;
  uint8_t brightness;
};

Config config;
ESP8266WebServer server(80);
ESP8266HTTPUpdateServer httpUpdater;
DNSServer dnsServer;
WiFiUDP udp;

bool setupPortalActive = false;

enum TallyState { STATE_OFF, STATE_PREVIEW, STATE_PROGRAM, STATE_ERROR };
enum WiFiRecoveryState { WIFI_NORMAL, WIFI_SEARCHING, WIFI_CONNECTING };

TallyState currentState = STATE_OFF;
WiFiRecoveryState wifiRecoveryState = WIFI_SEARCHING;

bool identifyActive = false;
unsigned long identifyStart = 0;
unsigned long lastPoll = 0;
unsigned long lastGoodTally = 0;
unsigned long lastHeartbeat = 0;

unsigned long lastRoamCheck = 0;
unsigned long lastRoamAt = 0;
bool roamScanRunning = false;
bool roamInProgress = false;
bool roamTargetValid = false;
uint8_t roamTargetBssid[6] = {0,0,0,0,0,0};

bool recoveryScanRunning = false;
unsigned long recoveryConnectStart = 0;
unsigned long lastRecoveryScanAt = 0;

// Supervision / diagnostic
uint32_t roamCount = 0;
uint32_t wifiLossCount = 0;
uint32_t tricasterLossCount = 0;
unsigned long lastRoamCompletedAt = 0;
unsigned long lastTriCasterLatency = 0;

IPAddress broadcastIP(192, 168, 1, 255);

IPAddress savedIP() {
  return IPAddress(config.ip[0], config.ip[1], config.ip[2], config.ip[3]);
}

IPAddress gatewayIP() {
  return IPAddress(config.gateway[0], config.gateway[1], config.gateway[2], config.gateway[3]);
}

IPAddress subnetIP() {
  return IPAddress(config.subnet[0], config.subnet[1], config.subnet[2], config.subnet[3]);
}

IPAddress dnsIP() {
  return IPAddress(config.dns[0], config.dns[1], config.dns[2], config.dns[3]);
}

IPAddress tricasterIP() {
  return IPAddress(config.tricaster[0], config.tricaster[1], config.tricaster[2], config.tricaster[3]);
}

void copyIP(uint8_t target[4], const IPAddress& source) {
  for (int i = 0; i < 4; i++) target[i] = source[i];
}

void updateBroadcastIP() {
  IPAddress local = WiFi.localIP();
  IPAddress mask = WiFi.subnetMask();

  // En IP statique, certains firmwares renvoient 0.0.0.0 tres tot.
  if (local == IPAddress(0,0,0,0)) local = savedIP();
  if (mask == IPAddress(0,0,0,0)) mask = subnetIP();

  for (int i = 0; i < 4; i++) {
    broadcastIP[i] = local[i] | (uint8_t)(~mask[i]);
  }
}

void applyNetworkConfig() {
  if (config.dhcp) {
    WiFi.config(IPAddress(0,0,0,0), IPAddress(0,0,0,0), IPAddress(0,0,0,0));
  } else {
    WiFi.config(savedIP(), gatewayIP(), subnetIP(), dnsIP());
  }
}

void setDefaults() {
  memset(&config, 0, sizeof(config));
  config.magic = CONFIG_MAGIC;

  snprintf(config.name, sizeof(config.name), "TALLY-%02d", DEFAULT_TALLY_NUMBER);
  strlcpy(config.ssid, DEFAULT_WIFI_SSID, sizeof(config.ssid));
  strlcpy(config.wifiPassword, DEFAULT_WIFI_PASSWORD, sizeof(config.wifiPassword));
  strlcpy(config.adminToken, DEFAULT_ADMIN_TOKEN, sizeof(config.adminToken));

  config.dhcp = false;

  config.ip[0] = 192; config.ip[1] = 168; config.ip[2] = 1;
  config.ip[3] = 80 + constrain(DEFAULT_TALLY_NUMBER, 1, 8);

  config.gateway[0] = 192; config.gateway[1] = 168; config.gateway[2] = 1; config.gateway[3] = 1;
  config.subnet[0] = 255; config.subnet[1] = 255; config.subnet[2] = 255; config.subnet[3] = 0;
  config.dns[0] = 192; config.dns[1] = 168; config.dns[2] = 1; config.dns[3] = 1;

  config.tricaster[0] = 192; config.tricaster[1] = 168;
  config.tricaster[2] = 1; config.tricaster[3] = 50;

  config.camera = constrain(DEFAULT_TALLY_NUMBER, 1, 8);

  config.pgmR = 255; config.pgmG = 0; config.pgmB = 0;
  config.prevR = 0; config.prevG = 255; config.prevB = 0;
  config.brightness = 100;
}

void saveConfig() {
  EEPROM.put(0, config);
  EEPROM.commit();
}

void migrateLegacyConfig(const LegacyConfigV3& legacy) {
  setDefaults();

  strlcpy(config.name, legacy.name, sizeof(config.name));
  memcpy(config.ip, legacy.ip, sizeof(config.ip));
  memcpy(config.tricaster, legacy.tricaster, sizeof(config.tricaster));

  config.camera = legacy.camera;
  config.pgmR = legacy.pgmR; config.pgmG = legacy.pgmG; config.pgmB = legacy.pgmB;
  config.prevR = legacy.prevR; config.prevG = legacy.prevG; config.prevB = legacy.prevB;
  config.brightness = legacy.brightness;

  config.magic = CONFIG_MAGIC;
  saveConfig();

  Serial.println("[CONFIG] Ancienne configuration migree vers V4");
}

void loadConfig() {
  EEPROM.begin(1024);

  uint32_t storedMagic = 0;
  EEPROM.get(0, storedMagic);

  if (storedMagic == CONFIG_MAGIC) {
    EEPROM.get(0, config);
  } else if (storedMagic == LEGACY_CONFIG_MAGIC) {
    LegacyConfigV3 legacy;
    EEPROM.get(0, legacy);
    migrateLegacyConfig(legacy);
  } else {
    setDefaults();
    saveConfig();
  }

  config.name[sizeof(config.name) - 1] = '\0';
  config.ssid[sizeof(config.ssid) - 1] = '\0';
  config.wifiPassword[sizeof(config.wifiPassword) - 1] = '\0';
  config.adminToken[sizeof(config.adminToken) - 1] = '\0';
}

void setRGBPWM(int r, int g, int b) {
  float factor = constrain(config.brightness, 1, 100) / 100.0;
  int rr = map((int)(constrain(r, 0, 255) * factor), 0, 255, 0, 1023);
  int gg = map((int)(constrain(g, 0, 255) * factor), 0, 255, 0, 1023);
  int bb = map((int)(constrain(b, 0, 255) * factor), 0, 255, 0, 1023);
  analogWrite(PIN_RED, 1023 - rr);
  analogWrite(PIN_GREEN, 1023 - gg);
  analogWrite(PIN_BLUE, 1023 - bb);
}

void ledsOff() { setRGBPWM(0, 0, 0); }

void fadeRGB(int r1, int g1, int b1, int r2, int g2, int b2, int durationMs) {
  const int steps = 30;
  for (int i = 0; i <= steps; i++) {
    float t = (float)i / steps;
    setRGBPWM(r1 + (r2-r1)*t, g1 + (g2-g1)*t, b1 + (b2-b1)*t);
    delay(durationMs / steps);
    yield();
  }
}

void startupAnimation() {
  fadeRGB(0,0,0, 255,0,0, 150);
  fadeRGB(255,0,0, 255,255,0, 150);
  fadeRGB(255,255,0, 0,255,0, 150);
  fadeRGB(0,255,0, 0,255,255, 150);
  fadeRGB(0,255,255, 0,0,255, 150);
  fadeRGB(0,0,255, 255,0,255, 150);
  fadeRGB(255,0,255, 0,0,0, 150);
  for (int i = 0; i < 3; i++) {
    setRGBPWM(255,255,255); delay(55); ledsOff(); delay(55); yield();
  }
}

void applyTallyLED() {
  if (currentState == STATE_PROGRAM) setRGBPWM(config.pgmR, config.pgmG, config.pgmB);
  else if (currentState == STATE_PREVIEW) setRGBPWM(config.prevR, config.prevG, config.prevB);
  else if (currentState == STATE_ERROR) setRGBPWM(255, 160, 0);
  else ledsOff();
}

void updateLED() {
  if (identifyActive) return;

  // Roaming volontaire : totalement invisible pour le cadreur.
  // On conserve strictement le dernier etat tally pendant le scan et la bascule.
  if (roamScanRunning || roamInProgress) {
    applyTallyLED();
    return;
  }

  // Vraie perte Wi-Fi : bleu fixe pendant la recherche du reseau.
  if (wifiRecoveryState == WIFI_SEARCHING) {
    setRGBPWM(0, 0, 255);
    return;
  }

  // SSID retrouve : bleu clignotant pendant la tentative d'association.
  if (wifiRecoveryState == WIFI_CONNECTING) {
    if ((millis() / BLUE_BLINK_INTERVAL) % 2) setRGBPWM(0, 0, 255);
    else ledsOff();
    return;
  }

  // Securite : si le lien tombe sans que la machine d'etat ait encore reagit.
  if (WiFi.status() != WL_CONNECTED) {
    setRGBPWM(0, 0, 255);
    return;
  }

  // Wi-Fi OK : rouge/vert/off selon le TriCaster, jaune si le TriCaster est perdu.
  applyTallyLED();
}

String jsonEscape(const String& value) {
  String out;
  out.reserve(value.length() + 8);
  for (unsigned int i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if ((uint8_t)c >= 32) out += c;
  }
  return out;
}

String stateName() {
  if (currentState == STATE_PROGRAM) return "program";
  if (currentState == STATE_PREVIEW) return "preview";
  if (currentState == STATE_ERROR) return "error";
  return "off";
}

String statusJSON() {
  String json = "{";
  json += "\"name\":\"" + jsonEscape(String(config.name)) + "\",";
  json += "\"firmware\":\"" + String(FIRMWARE_VERSION) + "\",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"static_ip\":\"" + savedIP().toString() + "\",";
  json += "\"dhcp\":" + String(config.dhcp ? "true" : "false") + ",";
  json += "\"gateway\":\"" + WiFi.gatewayIP().toString() + "\",";
  json += "\"subnet\":\"" + WiFi.subnetMask().toString() + "\",";
  json += "\"dns\":\"" + WiFi.dnsIP().toString() + "\",";
  json += "\"ssid\":\"" + jsonEscape(String(config.ssid)) + "\",";
  json += "\"tricaster\":\"" + tricasterIP().toString() + "\",";
  json += "\"camera\":" + String(config.camera) + ",";
  json += "\"state\":\"" + stateName() + "\",";
  json += "\"rssi\":" + String(WiFi.RSSI()) + ",";
  json += "\"bssid\":\"" + WiFi.BSSIDstr() + "\",";
  json += "\"channel\":" + String(WiFi.channel()) + ",";

  String wifiState = "connected";
  if (roamScanRunning || roamInProgress) wifiState = "roaming";
  else if (wifiRecoveryState == WIFI_SEARCHING) wifiState = "searching";
  else if (wifiRecoveryState == WIFI_CONNECTING) wifiState = "connecting";

  json += "\"wifi_state\":\"" + wifiState + "\",";
  json += "\"brightness\":" + String(config.brightness) + ",";
  json += "\"uptime_ms\":" + String(millis()) + ",";
  json += "\"tricaster_latency_ms\":" + String(lastTriCasterLatency) + ",";
  json += "\"last_tally_age_ms\":" + String(millis() - lastGoodTally) + ",";
  json += "\"roam_count\":" + String(roamCount) + ",";
  json += "\"wifi_loss_count\":" + String(wifiLossCount) + ",";
  json += "\"tricaster_loss_count\":" + String(tricasterLossCount) + ",";
  json += "\"last_roam_age_ms\":" + String(lastRoamCompletedAt == 0 ? 0 : millis() - lastRoamCompletedAt) + ",";
  json += "\"pgm\":[" + String(config.pgmR) + "," + String(config.pgmG) + "," + String(config.pgmB) + "],";
  json += "\"preview\":[" + String(config.prevR) + "," + String(config.prevG) + "," + String(config.prevB) + "]";
  json += "}";
  return json;
}

bool parseIPv4(const String& text, IPAddress& result) {
  int values[4] = {0,0,0,0};
  int part = 0;
  String token;
  for (unsigned int i = 0; i <= text.length(); i++) {
    char c = i < text.length() ? text[i] : '.';
    if (c == '.') {
      if (token.length() == 0 || part > 3) return false;
      for (unsigned int j = 0; j < token.length(); j++) if (!isDigit(token[j])) return false;
      values[part++] = token.toInt();
      token = "";
    } else token += c;
  }
  if (part != 4) return false;
  for (int i = 0; i < 4; i++) if (values[i] < 0 || values[i] > 255) return false;
  result = IPAddress(values[0], values[1], values[2], values[3]);
  return true;
}

bool parseTally(const String& data, bool& program, bool& preview) {
  String lower = data;
  lower.toLowerCase();

  String targetDouble = "name=\"input" + String(config.camera) + "\"";
  String targetSingle = "name='input" + String(config.camera) + "'";

  int namePos = lower.indexOf(targetDouble);
  if (namePos < 0) namePos = lower.indexOf(targetSingle);
  if (namePos < 0) return false;

  int tagStart = lower.lastIndexOf('<', namePos);
  int tagEnd = lower.indexOf('>', namePos);

  if (tagStart < 0 || tagEnd < 0 || tagEnd <= tagStart) return false;

  String tag = lower.substring(tagStart, tagEnd + 1);
  if (tag.indexOf("<column") < 0) return false;

  program = tag.indexOf("on_pgm=\"true\"") >= 0 || tag.indexOf("on_pgm='true'") >= 0;
  preview = tag.indexOf("on_prev=\"true\"") >= 0 || tag.indexOf("on_prev='true'") >= 0;

  return true;
}

bool readTriCaster() {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClient client;
  HTTPClient http;
  String url = "http://" + tricasterIP().toString() + "/v1/dictionary?key=tally";
  http.setTimeout(1000);

  if (!http.begin(client, url)) return false;

  unsigned long requestStart = millis();
  int response = http.GET();
  lastTriCasterLatency = millis() - requestStart;

  if (response != HTTP_CODE_OK) {
    http.end();
    return false;
  }

  String data = http.getString();
  http.end();

  bool pgm = false;
  bool preview = false;
  if (!parseTally(data, pgm, preview)) return false;

  TallyState newState = STATE_OFF;
  if (pgm) newState = STATE_PROGRAM;
  else if (preview) newState = STATE_PREVIEW;

  if (newState != currentState) {
    currentState = newState;
    Serial.println("[TALLY] CAM " + String(config.camera) + " -> " + stateName());
  } else {
    currentState = newState;
  }

  lastGoodTally = millis();
  updateLED();
  return true;
}

void sendHeartbeat() {
  String payload = statusJSON();
  udp.beginPacket(broadcastIP, 4210);
  udp.print(payload);
  udp.endPacket();
}

void handleStatus() {
  server.send(200, "application/json", statusJSON());
}

bool requireAdmin() {
  if (strlen(config.adminToken) == 0) return true;

  if (!server.authenticate("admin", config.adminToken)) {
    server.requestAuthentication();
    return false;
  }

  return true;
}

String htmlEscape(const String& value) {
  String out;
  out.reserve(value.length() + 16);

  for (unsigned int i = 0; i < value.length(); i++) {
    char ch = value[i];
    if (ch == '&') out += "&amp;";
    else if (ch == '<') out += "&lt;";
    else if (ch == '>') out += "&gt;";
    else if (ch == '"') out += "&quot;";
    else if (ch == '\'') out += "&#39;";
    else out += ch;
  }

  return out;
}

String setupPage() {
  String page;
  page.reserve(6000);

  page += "<!doctype html><html lang='fr'><head><meta charset='utf-8'>";
  page += "<meta name='viewport' content='width=device-width,initial-scale=1'>";
  page += "<title>Tally Wi-Fi Setup</title>";
  page += "<style>body{font-family:Arial;background:#111;color:#eee;margin:0;padding:18px}";
  page += ".box{max-width:640px;margin:auto;background:#202020;padding:18px;border-radius:12px}";
  page += "h1{font-size:24px;margin-top:0}label{display:block;margin-top:12px;color:#bbb;font-size:13px}";
  page += "input{width:100%;box-sizing:border-box;padding:10px;margin-top:4px;background:#111;color:#fff;border:1px solid #555;border-radius:7px}";
  page += ".row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:8px;align-items:center;margin-top:14px}.check input{width:auto;margin:0}";
  page += "button{width:100%;padding:12px;margin-top:18px;background:#2477d4;color:#fff;border:0;border-radius:8px;font-weight:bold}";
  page += ".note{color:#aaa;font-size:12px;line-height:1.45}.warn{color:#f4bd52}</style></head><body><div class='box'>";
  page += "<h1>TriCaster Tally - Configuration</h1>";
  page += "<p class='note'>Firmware " + String(FIRMWARE_VERSION) + ". Laissez les champs Mot de passe Wi-Fi et Token vides pour conserver les valeurs deja enregistrees.</p>";
  page += "<form method='POST' action='/setup-save'>";

  page += "<label>Nom du tally</label><input name='name' maxlength='31' value='" + htmlEscape(String(config.name)) + "' required>";
  page += "<label>SSID Wi-Fi 2,4 GHz</label><input name='ssid' maxlength='32' value='" + htmlEscape(String(config.ssid)) + "' required>";
  page += "<label>Mot de passe Wi-Fi</label><input name='wifi_password' type='password' maxlength='64' placeholder='laisser vide pour conserver'>";

  page += "<div class='check'><input id='dhcp' type='checkbox' name='dhcp' value='1'";
  if (config.dhcp) page += " checked";
  page += "><label for='dhcp' style='margin:0'>Utiliser DHCP</label></div>";

  page += "<div class='row'>";
  page += "<div><label>IP fixe</label><input name='ip' value='" + savedIP().toString() + "'></div>";
  page += "<div><label>Gateway</label><input name='gateway' value='" + gatewayIP().toString() + "'></div>";
  page += "<div><label>Subnet</label><input name='subnet' value='" + subnetIP().toString() + "'></div>";
  page += "<div><label>DNS</label><input name='dns' value='" + dnsIP().toString() + "'></div>";
  page += "</div>";

  page += "<label>IP TriCaster</label><input name='tricaster' value='" + tricasterIP().toString() + "' required>";
  page += "<label>Token administrateur</label><input name='admin_token' type='password' maxlength='32' placeholder='laisser vide pour conserver'>";
  page += "<p class='note warn'>Utilisez le meme token dans le Tally Manager. Changez la valeur par defaut CHANGE_ME avant une utilisation sur un reseau partage.</p>";
  page += "<button type='submit'>ENREGISTRER ET REDEMARRER</button></form></div></body></html>";

  return page;
}

void handleSetupPage() {
  if (!setupPortalActive && !requireAdmin()) return;
  server.send(200, "text/html", setupPage());
}

void handleSetupSave() {
  if (!setupPortalActive && !requireAdmin()) return;

  String newName = server.arg("name");
  String newSSID = server.arg("ssid");
  String newPassword = server.arg("wifi_password");
  String newToken = server.arg("admin_token");
  bool newDhcp = server.hasArg("dhcp") && server.arg("dhcp") == "1";

  IPAddress newIP, newGateway, newSubnet, newDNS, newTriCaster;

  if (newName.length() < 1 || newName.length() > 31) {
    server.send(400, "text/plain", "Nom invalide");
    return;
  }

  if (newSSID.length() < 1 || newSSID.length() > 32) {
    server.send(400, "text/plain", "SSID invalide");
    return;
  }

  if (!parseIPv4(server.arg("tricaster"), newTriCaster)) {
    server.send(400, "text/plain", "IP TriCaster invalide");
    return;
  }

  if (!newDhcp) {
    if (!parseIPv4(server.arg("ip"), newIP) ||
        !parseIPv4(server.arg("gateway"), newGateway) ||
        !parseIPv4(server.arg("subnet"), newSubnet) ||
        !parseIPv4(server.arg("dns"), newDNS)) {
      server.send(400, "text/plain", "Configuration IP statique invalide");
      return;
    }
  }

  newName.toCharArray(config.name, sizeof(config.name));
  newSSID.toCharArray(config.ssid, sizeof(config.ssid));

  if (newPassword.length() > 0) {
    newPassword.toCharArray(config.wifiPassword, sizeof(config.wifiPassword));
  }

  if (newToken.length() > 0) {
    if (newToken.length() < 8 || newToken.length() > 32) {
      server.send(400, "text/plain", "Token administrateur invalide (8 a 32 caracteres)");
      return;
    }
    newToken.toCharArray(config.adminToken, sizeof(config.adminToken));
  }

  config.dhcp = newDhcp;

  if (!newDhcp) {
    copyIP(config.ip, newIP);
    copyIP(config.gateway, newGateway);
    copyIP(config.subnet, newSubnet);
    copyIP(config.dns, newDNS);
  }

  copyIP(config.tricaster, newTriCaster);
  saveConfig();

  server.send(200, "text/html",
    "<!doctype html><html><body style='font-family:Arial;background:#111;color:#eee;padding:30px'>"
    "<h2>Configuration enregistree</h2><p>Le tally redemarre...</p></body></html>");

  delay(750);
  ESP.restart();
}

void handleCamera() {
  if (!requireAdmin()) return;

  int value = server.arg("value").toInt();
  if (value < 1 || value > 32) {
    server.send(400, "text/plain", "Camera invalide");
    return;
  }

  config.camera = value;
  saveConfig();
  server.send(200, "text/plain", "OK");
}

void handleBrightness() {
  if (!requireAdmin()) return;

  int value = constrain(server.arg("value").toInt(), 1, 100);
  config.brightness = value;
  saveConfig();
  updateLED();
  server.send(200, "text/plain", "OK");
}

void handleColors() {
  if (!requireAdmin()) return;

  config.pgmR = constrain(server.arg("pr").toInt(), 0, 255);
  config.pgmG = constrain(server.arg("pg").toInt(), 0, 255);
  config.pgmB = constrain(server.arg("pb").toInt(), 0, 255);
  config.prevR = constrain(server.arg("vr").toInt(), 0, 255);
  config.prevG = constrain(server.arg("vg").toInt(), 0, 255);
  config.prevB = constrain(server.arg("vb").toInt(), 0, 255);

  saveConfig();
  updateLED();
  server.send(200, "text/plain", "OK");
}

void handleIdentify() {
  if (!requireAdmin()) return;

  identifyActive = true;
  identifyStart = millis();
  server.send(200, "text/plain", "OK");
}

void handleConfig() {
  if (!requireAdmin()) return;

  String newName = server.arg("name");
  String newSSID = server.arg("ssid");
  String newPassword = server.arg("wifi_password");

  bool newDhcp = server.arg("dhcp") == "1";

  IPAddress newIP, newGateway, newSubnet, newDNS, newTriCaster;

  if (newName.length() < 1 || newName.length() > 31) {
    server.send(400, "text/plain", "Nom invalide");
    return;
  }

  if (newSSID.length() > 32) {
    server.send(400, "text/plain", "SSID invalide");
    return;
  }

  if (!parseIPv4(server.arg("tricaster"), newTriCaster)) {
    server.send(400, "text/plain", "IP TriCaster invalide");
    return;
  }

  if (!newDhcp) {
    if (!parseIPv4(server.arg("ip"), newIP) ||
        !parseIPv4(server.arg("gateway"), newGateway) ||
        !parseIPv4(server.arg("subnet"), newSubnet) ||
        !parseIPv4(server.arg("dns"), newDNS)) {
      server.send(400, "text/plain", "Configuration IP statique invalide");
      return;
    }
  }

  newName.toCharArray(config.name, sizeof(config.name));

  if (newSSID.length() > 0) {
    newSSID.toCharArray(config.ssid, sizeof(config.ssid));
  }

  if (newPassword.length() > 0) {
    newPassword.toCharArray(config.wifiPassword, sizeof(config.wifiPassword));
  }

  config.dhcp = newDhcp;

  if (!newDhcp) {
    copyIP(config.ip, newIP);
    copyIP(config.gateway, newGateway);
    copyIP(config.subnet, newSubnet);
    copyIP(config.dns, newDNS);
  }

  copyIP(config.tricaster, newTriCaster);

  saveConfig();
  server.send(200, "text/plain", "OK - redemarrage");
  delay(300);
  ESP.restart();
}

void handleReboot() {
  if (!requireAdmin()) return;

  server.send(200, "text/plain", "OK - redemarrage");
  delay(250);
  ESP.restart();
}

void setupRoutes() {
  server.on("/", HTTP_GET, []() {
    if (setupPortalActive) handleSetupPage();
    else server.send(200, "application/json", statusJSON());
  });

  server.on("/setup", HTTP_GET, handleSetupPage);
  server.on("/setup-save", HTTP_POST, handleSetupSave);

  server.on("/status", HTTP_GET, handleStatus);
  server.on("/camera", HTTP_GET, handleCamera);
  server.on("/brightness", HTTP_GET, handleBrightness);
  server.on("/colors", HTTP_GET, handleColors);
  server.on("/identify", HTTP_GET, handleIdentify);
  // POST est utilise par le Manager afin que le mot de passe Wi-Fi
  // ne soit pas place dans l'URL. GET reste accepte pour compatibilite.
  server.on("/config", HTTP_POST, handleConfig);
  server.on("/config", HTTP_GET, handleConfig);
  server.on("/reboot", HTTP_GET, handleReboot);

  // OTA HTTP standard : /update, authentifie en Basic admin:<token>.
  httpUpdater.setup(&server, "/update", "admin", config.adminToken);

  server.onNotFound([]() {
    if (setupPortalActive) {
      server.sendHeader("Location", "http://192.168.4.1/setup", true);
      server.send(302, "text/plain", "");
    } else {
      server.send(404, "text/plain", "Not found");
    }
  });

  server.begin();
}

void startSetupPortal() {
  setupPortalActive = true;

  WiFi.disconnect(false);
  WiFi.mode(WIFI_AP_STA);

  IPAddress apIP(192,168,4,1);
  IPAddress apMask(255,255,255,0);
  WiFi.softAPConfig(apIP, apIP, apMask);

  String apName = String(config.name) + "-SETUP";
  String setupPassword = strlen(config.adminToken) >= 8
                       ? String(config.adminToken)
                       : String(DEFAULT_ADMIN_TOKEN);

  WiFi.softAP(apName.c_str(), setupPassword.c_str());

  dnsServer.start(DNS_PORT, "*", apIP);

  wifiRecoveryState = WIFI_SEARCHING;
  updateLED();

  Serial.println();
  Serial.println("============================================");
  Serial.println("[SETUP] Aucun reseau joignable.");
  Serial.println("[SETUP] Connectez-vous au Wi-Fi : " + apName);
  Serial.println("[SETUP] Mot de passe : " + setupPassword);
  Serial.println("[SETUP] Ouvrez : http://192.168.4.1/");
  Serial.println("============================================");

  while (setupPortalActive) {
    dnsServer.processNextRequest();
    server.handleClient();
    updateLED();
    delay(2);
    yield();
  }
}


String formatBSSID(const uint8_t* bssid) {
  char buffer[18];
  snprintf(buffer, sizeof(buffer), "%02X:%02X:%02X:%02X:%02X:%02X",
           bssid[0], bssid[1], bssid[2], bssid[3], bssid[4], bssid[5]);
  return String(buffer);
}

bool sameBSSID(const uint8_t* a, const uint8_t* b) {
  if (!a || !b) return false;
  for (int i = 0; i < 6; i++) if (a[i] != b[i]) return false;
  return true;
}

int findBestSSID(int count, int& bestRssi) {
  int bestIndex = -1;
  bestRssi = -1000;

  for (int i = 0; i < count; i++) {
    if (WiFi.SSID(i) != config.ssid) continue;

    int rssi = WiFi.RSSI(i);
    if (bestIndex < 0 || rssi > bestRssi) {
      bestIndex = i;
      bestRssi = rssi;
    }
  }

  return bestIndex;
}

// =====================================================
// ROAMING VOLONTAIRE - INVISIBLE POUR LE CADREUR
// =====================================================

void startRoamScan() {
  if (roamScanRunning || roamInProgress || wifiRecoveryState != WIFI_NORMAL ||
      WiFi.status() != WL_CONNECTED) return;

  Serial.println("[WIFI] RSSI faible (" + String(WiFi.RSSI()) + " dBm) -> scan roaming");

  int result = WiFi.scanNetworks(true, false);
  if (result == WIFI_SCAN_RUNNING || result >= 0) {
    roamScanRunning = true;
    // Ne pas changer la LED : on garde le dernier etat tally.
    updateLED();
  } else {
    Serial.println("[WIFI] Impossible de demarrer le scan roaming");
    WiFi.scanDelete();
  }
}

void processRoamScan(unsigned long now) {
  if (!roamScanRunning) return;

  int count = WiFi.scanComplete();
  if (count == WIFI_SCAN_RUNNING) return;

  roamScanRunning = false;

  if (count < 0 || WiFi.status() != WL_CONNECTED) {
    WiFi.scanDelete();
    updateLED();
    return;
  }

  int currentRssi = WiFi.RSSI();
  uint8_t currentBssid[6];
  const uint8_t* connectedBssid = WiFi.BSSID();

  if (!connectedBssid) {
    WiFi.scanDelete();
    updateLED();
    return;
  }

  memcpy(currentBssid, connectedBssid, 6);

  int bestIndex = -1;
  int bestRssi = currentRssi;

  for (int i = 0; i < count; i++) {
    if (WiFi.SSID(i) != config.ssid) continue;

    const uint8_t* candidateBssid = WiFi.BSSID(i);
    if (!candidateBssid || sameBSSID(candidateBssid, currentBssid)) continue;

    int candidateRssi = WiFi.RSSI(i);
    if (candidateRssi > bestRssi) {
      bestRssi = candidateRssi;
      bestIndex = i;
    }
  }

  if (bestIndex >= 0 && bestRssi >= currentRssi + ROAM_MIN_GAIN) {
    uint8_t bestBssid[6];
    memcpy(bestBssid, WiFi.BSSID(bestIndex), 6);
    int32_t bestChannel = WiFi.channel(bestIndex);
    String targetBssid = formatBSSID(bestBssid);

    Serial.println("[WIFI] Roaming invisible " + WiFi.BSSIDstr() + " (" +
                   String(currentRssi) + " dBm) -> " + targetBssid + " (" +
                   String(bestRssi) + " dBm), canal " + String(bestChannel));

    WiFi.scanDelete();

    roamInProgress = true;
    roamTargetValid = true;
    memcpy(roamTargetBssid, bestBssid, 6);
    lastRoamAt = now;

    // IMPORTANT : aucune LED de connexion ici.
    // currentState reste intact et continue d'etre affiche pendant la bascule.
    updateLED();

    WiFi.disconnect(false);
    delay(10);
    applyNetworkConfig();
    WiFi.begin(config.ssid, config.wifiPassword, bestChannel, bestBssid, true);
    return;
  }

  // Le scan lui-meme peut interrompre brièvement les requetes HTTP.
  // On accorde donc un nouveau delai avant d'autoriser un jaune TriCaster.
  lastGoodTally = now;

  if (bestIndex >= 0) {
    Serial.println("[WIFI] Meilleur AP seulement +" + String(bestRssi - currentRssi) +
                   " dB -> pas de bascule");
  } else {
    Serial.println("[WIFI] Aucun meilleur AP avec le meme SSID");
  }

  WiFi.scanDelete();
  updateLED();
}

void handleRoaming(unsigned long now) {
  if (roamScanRunning) {
    processRoamScan(now);
    return;
  }

  if (roamInProgress || wifiRecoveryState != WIFI_NORMAL) return;
  if (now - lastRoamAt < ROAM_COOLDOWN) return;
  if (now - lastRoamCheck < ROAM_SCAN_INTERVAL) return;

  lastRoamCheck = now;

  if (WiFi.RSSI() <= ROAM_RSSI_TRIGGER) {
    startRoamScan();
  }
}

// =====================================================
// VRAIE PERTE WIFI : RECHERCHE / RECONNEXION VISIBLE
// =====================================================

void startWiFiRecovery(unsigned long now) {
  if (roamInProgress) return;

  wifiLossCount++;
  roamScanRunning = false;
  WiFi.scanDelete();

  recoveryScanRunning = false;
  wifiRecoveryState = WIFI_SEARCHING;
  lastRecoveryScanAt = 0;
  recoveryConnectStart = 0;

  Serial.println("[WIFI] Liaison perdue -> recherche du reseau");
  updateLED(); // bleu fixe
}

void startRecoveryScan(unsigned long now) {
  if (recoveryScanRunning || WiFi.status() == WL_CONNECTED) return;

  wifiRecoveryState = WIFI_SEARCHING;
  lastRecoveryScanAt = now;
  updateLED(); // bleu fixe

  int result = WiFi.scanNetworks(true, false);
  if (result == WIFI_SCAN_RUNNING || result >= 0) {
    recoveryScanRunning = true;
  } else {
    WiFi.scanDelete();
  }
}

void processRecovery(unsigned long now) {
  if (wifiRecoveryState == WIFI_CONNECTING) {
    if (WiFi.status() == WL_CONNECTED) {
      wifiRecoveryState = WIFI_NORMAL;
      recoveryConnectStart = 0;
      updateBroadcastIP();

      // On laisse 2 s au TriCaster pour repondre avant un eventuel jaune.
      lastGoodTally = now;

      Serial.println("[WIFI] Reconnexion terminee -> " + WiFi.BSSIDstr() +
                     " / canal " + String(WiFi.channel()) +
                     " / RSSI " + String(WiFi.RSSI()) + " dBm");

      updateLED();
      return;
    }

    if (now - recoveryConnectStart >= WIFI_CONNECT_TIMEOUT) {
      Serial.println("[WIFI] Echec de connexion -> nouvelle recherche");
      WiFi.disconnect(false);
      wifiRecoveryState = WIFI_SEARCHING;
      recoveryConnectStart = 0;
      lastRecoveryScanAt = 0;
      updateLED();
      return;
    }

    // Bleu clignotant pendant l'association.
    updateLED();
    return;
  }

  if (wifiRecoveryState != WIFI_SEARCHING) return;

  // Bleu fixe pendant toute la recherche.
  updateLED();

  if (recoveryScanRunning) {
    int count = WiFi.scanComplete();
    if (count == WIFI_SCAN_RUNNING) return;

    recoveryScanRunning = false;

    if (count >= 0) {
      int bestRssi;
      int bestIndex = findBestSSID(count, bestRssi);

      if (bestIndex >= 0) {
        uint8_t bestBssid[6];
        memcpy(bestBssid, WiFi.BSSID(bestIndex), 6);
        int32_t bestChannel = WiFi.channel(bestIndex);
        String targetBssid = formatBSSID(bestBssid);

        WiFi.scanDelete();

        Serial.println("[WIFI] Reseau retrouve -> connexion a " + targetBssid +
                       " / canal " + String(bestChannel) +
                       " / RSSI " + String(bestRssi) + " dBm");

        applyNetworkConfig();
        WiFi.begin(config.ssid, config.wifiPassword, bestChannel, bestBssid, true);

        wifiRecoveryState = WIFI_CONNECTING;
        recoveryConnectStart = now;
        updateLED(); // debut du bleu clignotant
        return;
      }
    }

    WiFi.scanDelete();
    Serial.println("[WIFI] Reseau introuvable -> poursuite de la recherche");
  }

  if (!recoveryScanRunning &&
      (lastRecoveryScanAt == 0 || now - lastRecoveryScanAt >= WIFI_SCAN_RETRY)) {
    startRecoveryScan(now);
  }
}

// =====================================================
// CONNEXION INITIALE
// =====================================================

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);

  // Le firmware gere lui-meme le roaming et la reconnexion.
  WiFi.setAutoReconnect(false);
  applyNetworkConfig();

  unsigned long startupStartedAt = millis();

  while (WiFi.status() != WL_CONNECTED) {
    wifiRecoveryState = WIFI_SEARCHING;
    updateLED();

    Serial.println("[WIFI] Recherche du reseau " + String(config.ssid));

    int count = WiFi.scanNetworks(false, false);
    int bestRssi;
    int bestIndex = findBestSSID(count, bestRssi);

    if (bestIndex >= 0) {
      uint8_t bestBssid[6];
      memcpy(bestBssid, WiFi.BSSID(bestIndex), 6);

      int32_t bestChannel = WiFi.channel(bestIndex);
      String targetBssid = formatBSSID(bestBssid);

      WiFi.scanDelete();

      Serial.println("[WIFI] Reseau trouve -> tentative de connexion a " +
                     targetBssid + " / canal " + String(bestChannel) +
                     " / RSSI " + String(bestRssi) + " dBm");

      applyNetworkConfig();

      WiFi.begin(
        config.ssid,
        config.wifiPassword,
        bestChannel,
        bestBssid,
        true
      );

      wifiRecoveryState = WIFI_CONNECTING;
      unsigned long connectStart = millis();

      while (WiFi.status() != WL_CONNECTED &&
             millis() - connectStart < WIFI_CONNECT_TIMEOUT) {
        updateLED();
        server.handleClient();
        delay(40);
        yield();
      }

      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WIFI] Echec de connexion -> nouvelle recherche");
        WiFi.disconnect(false);
        wifiRecoveryState = WIFI_SEARCHING;
        updateLED();
      }
    } else {
      WiFi.scanDelete();
    }

    if (WiFi.status() != WL_CONNECTED &&
        millis() - startupStartedAt >= STARTUP_SETUP_TIMEOUT) {
      startSetupPortal();
    }

    delay(250);
    yield();
  }

  wifiRecoveryState = WIFI_NORMAL;
  updateBroadcastIP();
  lastGoodTally = millis();

  Serial.println("[WIFI] Connecte a " + WiFi.BSSIDstr() +
                 " / canal " + String(WiFi.channel()) +
                 " / RSSI " + String(WiFi.RSSI()) + " dBm");
  Serial.println("[WIFI] IP : " + WiFi.localIP().toString() +
                 " / Gateway : " + WiFi.gatewayIP().toString());

  updateLED();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RED, OUTPUT); pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_BLUE, OUTPUT);
  analogWriteRange(1023); analogWriteFreq(1000);
  loadConfig(); ledsOff(); startupAnimation();
  setupRoutes();
  connectWiFi();
  udp.begin(4211);
  lastGoodTally = millis();
  Serial.println(); Serial.println("TRICASTER ELITE 2 WIFI TALLY");
  Serial.println(String(config.name) + " - " + WiFi.localIP().toString());
  Serial.println("TriCaster - " + tricasterIP().toString());
}

void loop() {
  server.handleClient();
  unsigned long now = millis();

  // Identification visuelle prioritaire.
  if (identifyActive) {
    if (now - identifyStart >= IDENTIFY_DURATION) {
      identifyActive = false;
      updateLED();
    } else {
      if ((now / 120) % 2) setRGBPWM(255,255,255);
      else setRGBPWM(255,0,255);
    }
  }

  // =================================================
  // ROAMING VOLONTAIRE
  // =================================================
  // Pendant toute cette phase on conserve le dernier rouge/vert/off/jaune.
  // Aucun bleu et aucun faux jaune ne sont montres au cadreur.
  if (roamInProgress) {
    const uint8_t* connectedBssid = WiFi.BSSID();
    bool targetReached = WiFi.status() == WL_CONNECTED &&
                         roamTargetValid &&
                         connectedBssid &&
                         sameBSSID(connectedBssid, roamTargetBssid);

    if (targetReached) {
      roamInProgress = false;
      roamTargetValid = false;
      roamCount++;
      lastRoamCompletedAt = now;
      updateBroadcastIP();
      lastGoodTally = now;

      Serial.println("[WIFI] Roaming termine -> " + WiFi.BSSIDstr() +
                     " / canal " + String(WiFi.channel()) +
                     " / RSSI " + String(WiFi.RSSI()) + " dBm");

      // Lecture immediate pour reprendre le vrai etat sans attendre le prochain cycle.
      readTriCaster();
      updateLED();
    } else if (now - lastRoamAt >= ROAM_CONNECT_TIMEOUT) {
      // Le roaming a reellement echoue : seulement maintenant on avertit le cadreur.
      roamInProgress = false;
      roamTargetValid = false;
      Serial.println("[WIFI] Roaming echoue -> passage en recherche Wi-Fi");
      startWiFiRecovery(now); // bleu fixe
    } else {
      updateLED(); // conserve le dernier tally
      delay(2);
      return;
    }
  }

  // =================================================
  // VRAIE PERTE WIFI
  // =================================================
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiRecoveryState == WIFI_NORMAL) {
      startWiFiRecovery(now);
    }

    processRecovery(now);
    delay(2);
    return;
  }

  // Une reconnexion peut devenir WL_CONNECTED avant le prochain passage.
  if (wifiRecoveryState != WIFI_NORMAL) {
    processRecovery(now);

    if (wifiRecoveryState != WIFI_NORMAL) {
      delay(2);
      return;
    }
  }

  // =================================================
  // WIFI OK : ROAMING PREVENTIF
  // =================================================
  handleRoaming(now);

  // Si handleRoaming vient de lancer une bascule, on gele l'affichage tally.
  if (roamInProgress || WiFi.status() != WL_CONNECTED) {
    updateLED();
    delay(2);
    return;
  }

  // =================================================
  // POLLING TRICASTER
  // =================================================
  if (now - lastPoll >= POLL_INTERVAL) {
    lastPoll = now;
    readTriCaster();
  }

  // Pendant un scan de roaming, on ne genere jamais de faux jaune.
  if (!roamScanRunning &&
      millis() - lastGoodTally > TALLY_TIMEOUT &&
      currentState != STATE_ERROR) {
    currentState = STATE_ERROR;
    tricasterLossCount++;
    Serial.println("[TALLY] Wi-Fi OK mais perte des donnees TriCaster -> jaune");
    updateLED();
  }

  // =================================================
  // HEARTBEAT MANAGER
  // =================================================
  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;
    sendHeartbeat();
  }

  delay(2);
}
