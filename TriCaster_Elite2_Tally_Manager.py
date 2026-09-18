"""TriCaster Elite 2 Tally Manager - production V4.

Multi-AP diagnostics, persistent configuration, authenticated ESP control,
network configuration and fleet OTA updates.
"""

import base64
import hmac
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_PORT = 8099
UDP_PORT = 4210
OFFLINE_AFTER = 3.5
MAX_OTA_SIZE = 4 * 1024 * 1024

APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
CONFIG_FILE = APP_DIR / "tally_manager_config.json"

devices = {}
devices_lock = threading.Lock()
config_lock = threading.Lock()

manager_config = {
    "api_token": "CHANGE_ME",
    "ap_aliases": {}
}


def load_manager_config():
    global manager_config
    try:
        existed = CONFIG_FILE.exists()
        if existed:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manager_config.update(loaded)
        if not isinstance(manager_config.get("ap_aliases"), dict):
            manager_config["ap_aliases"] = {}
        if not manager_config.get("api_token"):
            manager_config["api_token"] = "CHANGE_ME"
        if not existed:
            save_manager_config()
    except Exception as error:
        print(f"[CONFIG] Impossible de lire {CONFIG_FILE.name}: {error}")


def save_manager_config():
    with config_lock:
        CONFIG_FILE.write_text(
            json.dumps(manager_config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


def current_token():
    with config_lock:
        return str(manager_config.get("api_token") or "CHANGE_ME")


def basic_auth_header(token=None):
    token = current_token() if token is None else str(token)
    raw = f"admin:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111111">
<title>TriCaster Elite 2 Tally Manager V4</title>
<style>
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:0;padding:12px;min-height:100vh}
.wrap{max-width:1500px;margin:auto}
.header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:10px}
h1{margin:0;font-size:clamp(21px,3vw,29px)}
.sub{color:#aaa;font-size:13px;margin-top:3px}
.access{background:#17251b;border:1px solid #315d3a;border-radius:9px;padding:8px 11px;color:#ccebd2;font-size:12px;max-width:430px}
.access strong{display:inline;margin-right:6px}.access-url{color:#7ee397;overflow-wrap:anywhere}
#list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.card{background:#202020;border:1px solid #333;border-radius:10px;padding:11px;min-width:0}
.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}
.name{font-size:17px;font-weight:700}.online{color:#4bd36b}.offline{color:#e35555}
.meta{color:#aaa;font-size:12px;margin-top:3px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:9px;align-items:end}
label{display:block;color:#bbb;font-size:11px;margin-bottom:3px}
select,input[type=range],input[type=color],input[type=text]{width:100%}
select,input[type=text]{background:#151515;color:#eee;border:1px solid #444;border-radius:7px;padding:7px;font-size:14px}
input[type=color]{height:34px;background:#151515;border:1px solid #444;border-radius:7px;padding:2px}
input[type=range]{min-height:30px;touch-action:pan-y}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:9px}
button{border:0;border-radius:7px;padding:7px 5px;min-height:34px;font-size:11px;font-weight:700;cursor:pointer;touch-action:manipulation}
.ident{background:#7048bd;color:white}.reboot{background:#e29122;color:#111}.save{background:#2775c9;color:#fff}
.config{margin-top:8px;border-top:1px solid #383838;padding-top:7px}
.config summary{cursor:pointer;color:#aaa;font-size:12px;font-weight:700;touch-action:manipulation}
.config-grid{display:grid;grid-template-columns:1fr 1fr auto;gap:7px;align-items:end;margin-top:7px}
button:disabled{opacity:.45;cursor:not-allowed}
.state{font-weight:700}.program{color:#ff5757}.preview{color:#4bd36b}.error{color:#f0a020}.idle{color:#aaa}
.empty{padding:30px;text-align:center;color:#888;grid-column:1/-1}
.tools{display:grid;grid-template-columns:1.4fr 1fr auto;gap:10px;align-items:center;background:#181818;border:1px solid #333;border-radius:10px;padding:10px;margin-bottom:10px}
.rssi-good{color:#58d67b}.rssi-warn{color:#f0b84d}.rssi-bad{color:#ff6666}.diag{margin-top:5px;line-height:1.45}
@media(max-width:650px){body{padding:8px}.header{display:block}.access{margin-top:7px;max-width:none}.tools{grid-template-columns:1fr}.grid{gap:6px}#list{grid-template-columns:1fr}.config-grid{grid-template-columns:1fr 1fr}.config-grid button{grid-column:1/-1}}
</style>
</head>
<body>
<div class="wrap">
<div class="header"><div><h1>TriCaster Elite 2 Tally Manager</h1>
<div class="sub">Version V4 — multi-AP · diagnostic · réseau · OTA</div></div>
<div class="access"><strong>Accès téléphone :</strong><span class="access-url" id="access-url"></span></div></div>
<div class="tools">
  <div><strong>Firmware OTA</strong><div class="sub">Sélectionner un .bin ESP8266 puis mettre à jour tous les tally actuellement connectés.</div></div>
  <input type="file" id="firmwareFile" accept=".bin,application/octet-stream">
  <button class="save" onclick="uploadFirmware()">METTRE À JOUR TOUS LES TALLY</button>
  <span id="otaStatus" class="sub"></span>
</div>
<div id="list"><div class="empty">Recherche des tally…</div></div>
</div>
<script>
let editingBrightness = {};
let brightnessTimers = {};
document.getElementById('access-url').textContent = window.location.origin + '/mobile';
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function jsq(s){return JSON.stringify(String(s))}
function rgbHex(v){if(!Array.isArray(v)) return '#000000';return '#'+v.map(x=>Math.max(0,Math.min(255,Number(x)||0)).toString(16).padStart(2,'0')).join('')}
async function api(name,action,params={}){const q=new URLSearchParams({name,action,...params});const r=await fetch('/api?'+q.toString(),{cache:'no-store'});if(!r.ok) alert(await r.text())}
function sendBrightness(name,value){const output=document.getElementById('bv-'+name);if(output) output.textContent=value+'%';clearTimeout(brightnessTimers[name]);brightnessTimers[name]=setTimeout(()=>api(name,'brightness',{value}),100)}
function humanMs(ms){ms=Number(ms)||0;if(ms<1000)return ms+' ms';let s=Math.floor(ms/1000);if(s<60)return s+' s';let m=Math.floor(s/60);if(m<60)return m+' min';let h=Math.floor(m/60);if(h<48)return h+' h';return Math.floor(h/24)+' j'}
function rssiClass(v){v=Number(v);if(v>=-65)return'rssi-good';if(v>=-72)return'rssi-warn';return'rssi-bad'}
async function uploadFirmware(){
  const input=document.getElementById('firmwareFile'), status=document.getElementById('otaStatus');
  const file=input.files&&input.files[0];
  if(!file)return alert('Sélectionne un fichier .bin.');
  if(!confirm('Mettre à jour tous les tally actuellement connectés avec '+file.name+' ?'))return;
  status.textContent='Mise à jour en cours…';
  try{
    const r=await fetch('/ota-upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':file.name},body:file});
    const text=await r.text();status.textContent=text;if(!r.ok)alert(text);
  }catch(e){status.textContent='Erreur OTA : '+e}
}
async function saveSettings(name){const cam=document.getElementById('cam-'+name), pgm=document.getElementById('pgm-'+name), prev=document.getElementById('prev-'+name);if(cam&&pgm&&prev) await api(name,'save',{camera:cam.value,pgm:pgm.value,preview:prev.value})}
async function saveNetwork(oldName){
  const g=id=>document.getElementById(id+'-'+oldName);
  const newName=g('new-name').value.trim(), dhcp=g('dhcp').checked?'1':'0';
  const params={new_name:newName,dhcp,ssid:g('ssid').value.trim(),wifi_password:g('wifi-pass').value,
    new_ip:g('new-ip').value.trim(),gateway:g('gateway').value.trim(),subnet:g('subnet').value.trim(),
    dns:g('dns').value.trim(),tricaster:g('tricaster').value.trim()};
  if(!newName)return alert('Le nom est obligatoire.');
  if(!confirm('Appliquer la configuration réseau à '+oldName+' ? Le tally va redémarrer.'))return;
  await api(oldName,'config',params);
}
async function saveApAlias(name){
  const input=document.getElementById('ap-alias-'+name);
  if(!input)return;
  await api(name,'ap_alias',{alias:input.value.trim()});
}
function card(d){
  const online=d.online, disabled=online?'':'disabled';
  const stateClass=d.state==='program'?'program':d.state==='preview'?'preview':d.state==='error'?'error':'idle';
  const pgm=rgbHex(d.pgm||[255,0,0]), prev=rgbHex(d.preview||[0,255,0]);
  const name=String(d.name), safeName=esc(name), quotedName=jsq(name);
  let cams='';for(let i=1;i<=32;i++) cams+=`<option value="${i}" ${Number(d.camera)===i?'selected':''}>CAM ${i}</option>`;

  const rssi=Number(d.rssi??-100), rssiText=online?`${rssi} dBm`:'--';
  const channelText=online&&d.channel?`CH ${d.channel}`:'CH --';
  const bssidText=online&&d.bssid?String(d.bssid):'--:--:--:--:--:--';
  const apLabel=d.ap_name||bssidText;
  const wifiLabels={connected:'Wi-Fi OK',roaming:'ROAMING',searching:'RECHERCHE Wi-Fi',connecting:'CONNEXION Wi-Fi'};
  const wifiText=wifiLabels[d.wifi_state]||String(d.wifi_state||'Wi-Fi OK');
  const latency=d.tricaster_latency_ms??'-';
  const uptime=humanMs(d.uptime_ms);
  const losses=`Wi-Fi ${d.wifi_loss_count??0} · TriCaster ${d.tricaster_loss_count??0} · roam ${d.roam_count??0}`;

  return `<div class="card">
    <div class="top"><div><div class="name">${safeName}</div>
      <div class="meta">${esc(d.ip||'-')} · <span class="${rssiClass(rssi)}">RSSI ${rssiText}</span> · ${esc(channelText)}</div>
      <div class="meta">AP : ${esc(apLabel)}${d.ap_name?` · ${esc(bssidText)}`:''} · ${esc(wifiText)}</div>
      <div class="meta diag">FW ${esc(d.firmware||'?')} · TriCaster ${esc(String(latency))} ms · uptime ${esc(uptime)} · pertes : ${esc(losses)}</div>
    </div><div class="${online?'online':'offline'}">● ${online?'CONNECTÉ':'HORS LIGNE'}</div></div>
    <div class="meta">État : <span class="state ${stateClass}">${esc((d.state||'off').toUpperCase())}</span></div>

    <div class="grid">
      <div><label>Caméra attribuée</label><select id="cam-${safeName}" onchange='saveSettings(${quotedName})' ${disabled}>${cams}</select></div>
      <div><label>Couleur PROGRAM</label><input type="color" id="pgm-${safeName}" value="${pgm}" onchange='saveSettings(${quotedName})' ${disabled}></div>
      <div><label>Luminosité : <span id="bv-${safeName}">${d.brightness??100}%</span></label><input type="range" min="1" max="100" value="${d.brightness??100}" id="b-${safeName}" onpointerdown='editingBrightness[${quotedName}]=true' onpointerup='editingBrightness[${quotedName}]=false' onpointercancel='editingBrightness[${quotedName}]=false' oninput='sendBrightness(${quotedName},this.value)' ${disabled}></div>
      <div><label>Couleur PREVIEW</label><input type="color" id="prev-${safeName}" value="${prev}" onchange='saveSettings(${quotedName})' ${disabled}></div>
    </div>

    <div class="actions"><button class="ident" ${disabled} onclick='api(${quotedName},"identify")'>IDENTIFY</button><button class="reboot" ${disabled} onclick='if(confirm("Redémarrer "+${quotedName}+" ?")) api(${quotedName},"reboot")'>REBOOT</button></div>

    <details class="config" data-tally="${safeName}"><summary>CONFIGURATION RÉSEAU / BOÎTIER</summary>
      <div class="config-grid">
        <div><label>Nom / cadreur</label><input type="text" id="new-name-${safeName}" maxlength="31" value="${safeName}" ${disabled}></div>
        <div><label>SSID</label><input type="text" id="ssid-${safeName}" maxlength="32" value="${esc(d.ssid||'')}" ${disabled}></div>
        <div><label>Mot de passe Wi-Fi (vide = inchangé)</label><input type="password" id="wifi-pass-${safeName}" maxlength="64" ${disabled}></div>
        <div><label>TriCaster</label><input type="text" id="tricaster-${safeName}" value="${esc(d.tricaster||'192.168.1.50')}" ${disabled}></div>
        <div><label><input type="checkbox" id="dhcp-${safeName}" ${d.dhcp?'checked':''} ${disabled}> DHCP</label></div>
        <div><label>Adresse IP fixe</label><input type="text" id="new-ip-${safeName}" value="${esc(d.ip||'192.168.1.81')}" ${disabled}></div>
        <div><label>Gateway</label><input type="text" id="gateway-${safeName}" value="${esc(d.gateway||'192.168.1.1')}" ${disabled}></div>
        <div><label>Subnet</label><input type="text" id="subnet-${safeName}" value="${esc(d.subnet||'255.255.255.0')}" ${disabled}></div>
        <div><label>DNS</label><input type="text" id="dns-${safeName}" value="${esc(d.dns||d.gateway||'192.168.1.1')}" ${disabled}></div>
        <button class="save" ${disabled} onclick='saveNetwork(${quotedName})'>ENREGISTRER RÉSEAU</button>
      </div>
      <div class="config-grid">
        <div><label>Nom convivial de l'AP actuel</label><input type="text" id="ap-alias-${safeName}" value="${esc(d.ap_name||'')}" placeholder="ex. AP TERRAIN" ${disabled}></div>
        <div><label>BSSID</label><input type="text" value="${esc(bssidText)}" disabled></div>
        <button class="save" ${disabled} onclick='saveApAlias(${quotedName})'>NOMMER CET AP</button>
      </div>
    </details>
  </div>`;
}

async function refresh(){try{const r=await fetch('/devices',{cache:'no-store'}), ds=await r.json();const someoneEditing=Object.values(editingBrightness).some(v=>v===true), active=document.activeElement;const controlFocused=active&&(active.tagName==='INPUT'||active.tagName==='SELECT');if(someoneEditing||controlFocused)return;const openConfigs=new Set([...document.querySelectorAll('details.config[open]')].map(el=>el.dataset.tally).filter(Boolean));document.getElementById('list').innerHTML=ds.length?ds.map(card).join(''):'<div class="empty">Aucun tally détecté.</div>';document.querySelectorAll('details.config').forEach(el=>{if(openConfigs.has(el.dataset.tally)) el.open=true})}catch(e){}}
refresh();setInterval(refresh,1000);
</script>
</body>
</html>"""

def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError("invalid color")
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))

def esp_get(ip, path, timeout=1.0, token=None):
    request = urllib.request.Request(
        f"http://{ip}{path}",
        headers={"Authorization": basic_auth_header(token)}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def esp_post_form(ip, path, params, timeout=2.0, token=None):
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        f"http://{ip}{path}",
        data=data,
        method="POST",
        headers={
            "Authorization": basic_auth_header(token),
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def push_ota(ip, firmware, token=None, timeout=25.0):
    boundary = "----TallyManagerOTA" + str(int(time.time() * 1000))
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="update"; filename="firmware.bin"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = prefix + firmware + suffix

    request = urllib.request.Request(
        f"http://{ip}/update",
        data=body,
        method="POST",
        headers={
            "Authorization": basic_auth_header(token),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body))
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")

def refresh_device_details(ip, name):
    try:
        info = json.loads(esp_get(ip, "/status", timeout=0.8))
        with devices_lock:
            if name in devices:
                devices[name].update(info)
    except Exception:
        pass

def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", UDP_PORT))
    print(f"[UDP] écoute des tally sur le port {UDP_PORT}")
    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = json.loads(data.decode("utf-8"))
            name = msg.get("name")
            if not name:
                continue
            msg["ip"] = msg.get("ip") or addr[0]
            msg["last_seen"] = time.time()
            with devices_lock:
                first_seen = name not in devices
                old = devices.get(name, {})
                old.update(msg)
                devices[name] = old
            if first_seen:
                threading.Thread(target=refresh_device_details, args=(msg["ip"], name), daemon=True).start()
                print(f"[TALLY] {name} détecté à {msg['ip']}")
        except Exception:
            pass

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_text(self, code, content, ctype):
        body = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def manager_authorized(self):
        received = self.headers.get("Authorization", "")
        expected = basic_auth_header()
        return hmac.compare_digest(received, expected)

    def require_manager_auth(self):
        if self.manager_authorized():
            return True

        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="TriCaster Tally Manager"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        if not self.require_manager_auth():
            return

        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ("/", "/mobile", "/mobile/"):
            self.send_text(200, PAGE, "text/html")
            return

        if parsed.path == "/devices":
            now = time.time()
            with config_lock:
                aliases = dict(manager_config.get("ap_aliases", {}))

            with devices_lock:
                result = []
                for name, device in sorted(devices.items()):
                    item = dict(device)
                    item["online"] = (now - item.get("last_seen", 0)) <= OFFLINE_AFTER
                    bssid = str(item.get("bssid") or "")
                    item["ap_name"] = aliases.get(bssid, "")
                    result.append(item)

            self.send_text(200, json.dumps(result, ensure_ascii=False), "application/json")
            return

        if parsed.path == "/api":
            q = urllib.parse.parse_qs(parsed.query)
            name = q.get("name", [""])[0]
            action = q.get("action", [""])[0]

            if action == "ap_alias":
                with devices_lock:
                    device = dict(devices.get(name, {}))
                bssid = str(device.get("bssid") or "").strip()
                if not bssid:
                    self.send_text(400, "BSSID indisponible", "text/plain")
                    return

                alias = q.get("alias", [""])[0].strip()
                with config_lock:
                    aliases = manager_config.setdefault("ap_aliases", {})
                    if alias:
                        aliases[bssid] = alias
                    else:
                        aliases.pop(bssid, None)
                save_manager_config()
                self.send_text(200, "OK", "text/plain")
                return

            with devices_lock:
                device = dict(devices.get(name, {}))

            if not device or not device.get("ip"):
                self.send_text(404, "Tally inconnu", "text/plain")
                return

            ip = device["ip"]

            try:
                if action == "brightness":
                    value = max(1, min(100, int(q.get("value", ["100"])[0])))
                    esp_get(ip, "/brightness?" + urllib.parse.urlencode({"value": value}))
                    with devices_lock:
                        if name in devices:
                            devices[name]["brightness"] = value

                elif action == "identify":
                    esp_get(ip, "/identify")

                elif action == "reboot":
                    try:
                        esp_get(ip, "/reboot")
                    except Exception:
                        # La socket peut etre fermee pendant le redemarrage.
                        pass

                elif action == "config":
                    new_name = q.get("new_name", [""])[0].strip()
                    ssid = q.get("ssid", [""])[0].strip()
                    wifi_password = q.get("wifi_password", [""])[0]
                    dhcp = q.get("dhcp", ["0"])[0] == "1"
                    new_ip = q.get("new_ip", [""])[0].strip()
                    gateway = q.get("gateway", [""])[0].strip()
                    subnet = q.get("subnet", [""])[0].strip()
                    dns = q.get("dns", [""])[0].strip()
                    tricaster = q.get("tricaster", [""])[0].strip()

                    if not new_name or len(new_name) > 31:
                        raise ValueError("nom invalide (1 a 31 caracteres)")
                    if len(ssid) > 32:
                        raise ValueError("SSID invalide")
                    if not tricaster:
                        raise ValueError("IP TriCaster obligatoire")

                    try:
                        socket.inet_aton(tricaster)
                        if not dhcp:
                            socket.inet_aton(new_ip)
                            socket.inet_aton(gateway)
                            socket.inet_aton(subnet)
                            socket.inet_aton(dns)
                    except OSError:
                        raise ValueError("adresse IP invalide")

                    params = {
                        "name": new_name,
                        "ssid": ssid,
                        "wifi_password": wifi_password,
                        "dhcp": "1" if dhcp else "0",
                        "ip": new_ip,
                        "gateway": gateway,
                        "subnet": subnet,
                        "dns": dns,
                        "tricaster": tricaster
                    }

                    esp_post_form(ip, "/config", params, timeout=3.0)

                    with devices_lock:
                        if name in devices:
                            updated = devices.pop(name)
                            updated["name"] = new_name
                            if not dhcp and new_ip:
                                updated["ip"] = new_ip
                            updated["last_seen"] = 0
                            devices[new_name] = updated

                elif action == "save":
                    camera = max(1, min(32, int(q.get("camera", ["1"])[0])))
                    pgm = hex_to_rgb(q.get("pgm", ["#ff0000"])[0])
                    prev = hex_to_rgb(q.get("preview", ["#00ff00"])[0])

                    esp_get(ip, "/camera?" + urllib.parse.urlencode({"value": camera}))

                    params = {
                        "pr": pgm[0], "pg": pgm[1], "pb": pgm[2],
                        "vr": prev[0], "vg": prev[1], "vb": prev[2]
                    }
                    esp_get(ip, "/colors?" + urllib.parse.urlencode(params))
                    refresh_device_details(ip, name)

                else:
                    self.send_text(400, "Action inconnue", "text/plain")
                    return

                self.send_text(200, "OK", "text/plain")

            except Exception as error:
                self.send_text(502, f"Erreur communication ESP: {error}", "text/plain")

            return

        self.send_text(404, "Not found", "text/plain")

    def do_POST(self):
        if not self.require_manager_auth():
            return

        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/ota-upload":
            self.send_text(404, "Not found", "text/plain")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if length <= 0 or length > MAX_OTA_SIZE:
            self.send_text(400, "Taille firmware invalide", "text/plain")
            return

        firmware = self.rfile.read(length)

        if not firmware or firmware[0] != 0xE9:
            self.send_text(
                400,
                "Le fichier ne ressemble pas a un firmware ESP8266 .bin valide (magic 0xE9 absent).",
                "text/plain"
            )
            return

        now = time.time()
        with devices_lock:
            targets = [
                (name, str(device.get("ip")))
                for name, device in devices.items()
                if device.get("ip") and (now - device.get("last_seen", 0)) <= OFFLINE_AFTER
            ]

        if not targets:
            self.send_text(400, "Aucun tally connecte a mettre a jour.", "text/plain")
            return

        successes = []
        failures = []

        for name, ip in sorted(targets):
            try:
                push_ota(ip, firmware)
                successes.append(name)
                print(f"[OTA] {name} ({ip}) : firmware envoye")
            except Exception as error:
                failures.append(f"{name}: {error}")
                print(f"[OTA] {name} ({ip}) : ECHEC - {error}")

            # L'ESP redemarre apres la mise a jour. On espace legerement les envois.
            time.sleep(0.25)

        message = f"OTA terminee : {len(successes)}/{len(targets)} tally mis a jour."
        if failures:
            message += " Echecs : " + " | ".join(failures)

        self.send_text(200 if not failures else 207, message, "text/plain")

def get_local_ip():
    try:
        candidates = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for candidate in candidates:
            address = candidate[4][0]
            if not address.startswith("127."):
                return address
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()

def main():
    load_manager_config()
    threading.Thread(target=udp_listener, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    local_ip = get_local_ip()
    print()
    print("====================================")
    print("   TRICASTER ELITE 2 TALLY MANAGER V4")
    print("====================================")
    print(f"PC local          : http://127.0.0.1:{HTTP_PORT}")
    print(f"TÉLÉPHONE (Wi-Fi) : http://{local_ip}:{HTTP_PORT}/mobile")
    print("Le téléphone et le PC doivent être sur le même réseau.")
    print(f"Configuration     : {CONFIG_FILE}")
    print("Authentification  : utilisateur admin + token API configure")
    print("CTRL+C pour arrêter.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du manager.")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
