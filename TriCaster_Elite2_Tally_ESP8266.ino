#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPClient.h>
#include <WiFiUdp.h>
#include <EEPROM.h>

// =====================================================
// TRICASTER ELITE 2 WIFI TALLY - ESP8266
// Modifier uniquement ce numéro avant le premier flash.
// Exemple public : 1 = 192.168.1.81, 2 = .82, ... 8 = .88
// =====================================================
#define DEFAULT_TALLY_NUMBER 3

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

#define PIN_GREEN D1
#define PIN_RED   D2
#define PIN_BLUE  D3
#define LED_ON LOW
#define LED_OFF HIGH

const uint32_t CONFIG_MAGIC = 0xCA12AC06;
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

struct Config {
  uint32_t magic;
  char name[32];
  uint8_t ip[4];
  uint8_t tricaster[4];
  uint8_t camera;
  uint8_t pgmR, pgmG, pgmB;
  uint8_t prevR, prevG, prevB;
  uint8_t brightness;
};

Config config;
ESP8266WebServer server(80);
WiFiUDP udp;

enum TallyState { STATE_OFF, STATE_PREVIEW, STATE_PROGRAM, STATE_ERROR };
TallyState currentState = STATE_ERROR;
bool identifyActive = false;
unsigned long identifyStart = 0;
unsigned long lastPoll = 0;
unsigned long lastGoodTally = 0;
unsigned long lastHeartbeat = 0;
unsigned long lastRoamCheck = 0;
unsigned long lastRoamAt = 0;
bool roamScanRunning = false;
bool roamInProgress = false;

IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(192, 168, 1, 1);
IPAddress broadcastIP(192, 168, 1, 255);

IPAddress savedIP() {
  return IPAddress(config.ip[0], config.ip[1], config.ip[2], config.ip[3]);
}

IPAddress tricasterIP() {
  return IPAddress(config.tricaster[0], config.tricaster[1], config.tricaster[2], config.tricaster[3]);
}

void copyIP(uint8_t target[4], const IPAddress& source) {
  for (int i = 0; i < 4; i++) target[i] = source[i];
}

void setDefaults() {
  memset(&config, 0, sizeof(config));
  config.magic = CONFIG_MAGIC;
  snprintf(config.name, sizeof(config.name), "TALLY-%02d", DEFAULT_TALLY_NUMBER);
  config.ip[0] = 192; config.ip[1] = 168; config.ip[2] = 1;
  config.ip[3] = 80 + constrain(DEFAULT_TALLY_NUMBER, 1, 8);
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

void loadConfig() {
  EEPROM.begin(256);
  EEPROM.get(0, config);
  if (config.magic != CONFIG_MAGIC || config.name[0] == '\0') {
    setDefaults();
    saveConfig();
  }
  config.name[sizeof(config.name) - 1] = '\0';
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

void updateLED() {
  if (identifyActive) return;

  // Bleu pendant une perte Wi-Fi ou une bascule entre deux points d'acces.
  if (WiFi.status() != WL_CONNECTED || roamInProgress) {
    setRGBPWM(0, 0, 255);
    return;
  }

  if (currentState == STATE_PROGRAM) setRGBPWM(config.pgmR, config.pgmG, config.pgmB);
  else if (currentState == STATE_PREVIEW) setRGBPWM(config.prevR, config.prevG, config.prevB);
  else if (currentState == STATE_ERROR) setRGBPWM(255, 160, 0);
  else ledsOff();
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
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"tricaster\":\"" + tricasterIP().toString() + "\",";
  json += "\"camera\":" + String(config.camera) + ",";
  json += "\"state\":\"" + stateName() + "\",";
  json += "\"rssi\":" + String(WiFi.RSSI()) + ",";
  json += "\"bssid\":\"" + WiFi.BSSIDstr() + "\",";
  json += "\"channel\":" + String(WiFi.channel()) + ",";
  json += "\"brightness\":" + String(config.brightness) + ",";
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

  int response = http.GET();
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

void handleStatus() { server.send(200, "application/json", statusJSON()); }

void handleCamera() {
  int value = server.arg("value").toInt();
  if (value < 1 || value > 32) { server.send(400, "text/plain", "Camera invalide"); return; }
  config.camera = value; saveConfig();
  server.send(200, "text/plain", "OK");
}

void handleBrightness() {
  int value = constrain(server.arg("value").toInt(), 1, 100);
  config.brightness = value; saveConfig(); updateLED();
  server.send(200, "text/plain", "OK");
}

void handleColors() {
  config.pgmR = constrain(server.arg("pr").toInt(), 0, 255);
  config.pgmG = constrain(server.arg("pg").toInt(), 0, 255);
  config.pgmB = constrain(server.arg("pb").toInt(), 0, 255);
  config.prevR = constrain(server.arg("vr").toInt(), 0, 255);
  config.prevG = constrain(server.arg("vg").toInt(), 0, 255);
  config.prevB = constrain(server.arg("vb").toInt(), 0, 255);
  saveConfig(); updateLED();
  server.send(200, "text/plain", "OK");
}

void handleIdentify() {
  identifyActive = true; identifyStart = millis();
  server.send(200, "text/plain", "OK");
}

void handleConfig() {
  String newName = server.arg("name");
  IPAddress newIP, newTriCaster;
  if (newName.length() < 1 || newName.length() > 31) { server.send(400, "text/plain", "Nom invalide"); return; }
  if (!parseIPv4(server.arg("ip"), newIP) || !parseIPv4(server.arg("tricaster"), newTriCaster)) {
    server.send(400, "text/plain", "Adresse IP invalide"); return;
  }
  newName.toCharArray(config.name, sizeof(config.name));
  copyIP(config.ip, newIP); copyIP(config.tricaster, newTriCaster);
  saveConfig();
  server.send(200, "text/plain", "OK - redemarrage");
  delay(250); ESP.restart();
}

void handleReboot() {
  server.send(200, "text/plain", "OK - redemarrage");
  delay(250); ESP.restart();
}

void setupRoutes() {
  server.on("/status", handleStatus);
  server.on("/camera", handleCamera);
  server.on("/brightness", handleBrightness);
  server.on("/colors", handleColors);
  server.on("/identify", handleIdentify);
  server.on("/config", handleConfig);
  server.on("/reboot", handleReboot);
  server.onNotFound([](){ server.send(404, "text/plain", "Not found"); });
  server.begin();
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

void startRoamScan() {
  if (roamScanRunning || roamInProgress || WiFi.status() != WL_CONNECTED) return;

  Serial.println("[WIFI] RSSI faible (" + String(WiFi.RSSI()) + " dBm) -> scan roaming");
  int result = WiFi.scanNetworks(true, false);
  if (result == WIFI_SCAN_RUNNING || result >= 0) {
    roamScanRunning = true;
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
    return;
  }

  int currentRssi = WiFi.RSSI();
  uint8_t currentBssid[6];
  const uint8_t* connectedBssid = WiFi.BSSID();
  if (!connectedBssid) {
    WiFi.scanDelete();
    return;
  }
  memcpy(currentBssid, connectedBssid, 6);

  int bestIndex = -1;
  int bestRssi = currentRssi;

  for (int i = 0; i < count; i++) {
    if (WiFi.SSID(i) != WIFI_SSID) continue;

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

    Serial.println("[WIFI] Roaming " + WiFi.BSSIDstr() + " (" + String(currentRssi) +
                   " dBm) -> " + targetBssid + " (" + String(bestRssi) +
                   " dBm), canal " + String(bestChannel));

    WiFi.scanDelete();

    roamInProgress = true;
    lastRoamAt = now;
    setRGBPWM(0, 0, 255);

    WiFi.disconnect(false);
    delay(10);
    WiFi.config(savedIP(), gateway, subnet, dns);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD, bestChannel, bestBssid, true);
    return;
  }

  if (bestIndex >= 0) {
    Serial.println("[WIFI] Meilleur AP seulement +" + String(bestRssi - currentRssi) +
                   " dB -> pas de bascule");
  } else {
    Serial.println("[WIFI] Aucun meilleur AP avec le meme SSID");
  }

  WiFi.scanDelete();
}

void handleRoaming(unsigned long now) {
  if (roamScanRunning) {
    processRoamScan(now);
    return;
  }

  if (roamInProgress) return;
  if (now - lastRoamAt < ROAM_COOLDOWN) return;
  if (now - lastRoamCheck < ROAM_SCAN_INTERVAL) return;

  lastRoamCheck = now;

  if (WiFi.RSSI() <= ROAM_RSSI_TRIGGER) {
    startRoamScan();
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.config(savedIP(), gateway, subnet, dns);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    setRGBPWM(0, 0, 255); delay(180); ledsOff(); delay(180); yield();
  }

  Serial.println("[WIFI] Connecte a " + WiFi.BSSIDstr() +
                 " / canal " + String(WiFi.channel()) +
                 " / RSSI " + String(WiFi.RSSI()) + " dBm");
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RED, OUTPUT); pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_BLUE, OUTPUT);
  analogWriteRange(1023); analogWriteFreq(1000);
  loadConfig(); ledsOff(); startupAnimation(); connectWiFi();
  udp.begin(4211); setupRoutes();
  lastGoodTally = millis();
  Serial.println(); Serial.println("TRICASTER ELITE 2 WIFI TALLY");
  Serial.println(String(config.name) + " - " + WiFi.localIP().toString());
  Serial.println("TriCaster - " + tricasterIP().toString());
}

void loop() {
  server.handleClient();
  unsigned long now = millis();
  if (identifyActive) {
    if (now - identifyStart >= IDENTIFY_DURATION) { identifyActive = false; updateLED(); }
    else if ((now / 120) % 2) setRGBPWM(255,255,255); else setRGBPWM(255,0,255);
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (roamInProgress && now - lastRoamAt > ROAM_CONNECT_TIMEOUT) {
      roamInProgress = false;
      Serial.println("[WIFI] Roaming timeout -> reconnexion normale");
    }

    currentState = STATE_ERROR;
    updateLED();

    static unsigned long lastReconnect = 0;
    if (now - lastReconnect > 5000) {
      lastReconnect = now;
      WiFi.disconnect();
      WiFi.config(savedIP(), gateway, subnet, dns);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
  } else {
    if (roamInProgress) {
      roamInProgress = false;
      lastGoodTally = now;
      Serial.println("[WIFI] Roaming termine -> " + WiFi.BSSIDstr() +
                     " / canal " + String(WiFi.channel()) +
                     " / RSSI " + String(WiFi.RSSI()) + " dBm");
      updateLED();
    }

    handleRoaming(now);

    // handleRoaming() peut lancer une bascule et couper momentanement le Wi-Fi.
    if (WiFi.status() == WL_CONNECTED) {
      if (now - lastPoll >= POLL_INTERVAL) {
        lastPoll = now;
        readTriCaster();
      }

      if (millis() - lastGoodTally > TALLY_TIMEOUT && currentState != STATE_ERROR) {
        currentState = STATE_ERROR;
        Serial.println("[TALLY] Perte des donnees TriCaster -> error");
        updateLED();
      }

      if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
        lastHeartbeat = now;
        sendHeartbeat();
      }
    }
  }

  delay(2);
}
