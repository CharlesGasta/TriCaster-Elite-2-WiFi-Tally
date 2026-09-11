"""TriCaster Elite 2 Tally Manager - version finale de production V2."""

import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_PORT = 8099
UDP_PORT = 4210
OFFLINE_AFTER = 3.5

devices = {}
devices_lock = threading.Lock()

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111111">
<title>TriCaster Elite 2 Tally Manager FINAL V2</title>
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
@media(max-width:650px){body{padding:8px}.header{display:block}.access{margin-top:7px;max-width:none}.grid{gap:6px}#list{grid-template-columns:1fr}.config-grid{grid-template-columns:1fr 1fr}.config-grid button{grid-column:1/-1}}
</style>
</head>
<body>
<div class="wrap">
<div class="header"><div><h1>TriCaster Elite 2 Tally Manager</h1>
<div class="sub">Version finale V2 — administration des tally autonomes</div></div>
<div class="access"><strong>Accès téléphone :</strong><span class="access-url" id="access-url"></span></div></div>
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
async function saveSettings(name){const cam=document.getElementById('cam-'+name), pgm=document.getElementById('pgm-'+name), prev=document.getElementById('prev-'+name);if(cam&&pgm&&prev) await api(name,'save',{camera:cam.value,pgm:pgm.value,preview:prev.value})}
async function saveNetwork(oldName){const newName=document.getElementById('new-name-'+oldName).value.trim();const newIp=document.getElementById('new-ip-'+oldName).value.trim();if(!newName||!newIp)return alert('Le nom et l’adresse IP sont obligatoires.');if(!confirm('Appliquer '+newName+' sur '+newIp+' ? Le tally va redémarrer.'))return;await api(oldName,'config',{new_name:newName,new_ip:newIp,tricaster:'192.168.1.50'})}
function card(d){
  const online=d.online, disabled=online?'':'disabled';
  const stateClass=d.state==='program'?'program':d.state==='preview'?'preview':d.state==='error'?'error':'idle';
  const pgm=rgbHex(d.pgm||[255,0,0]), prev=rgbHex(d.preview||[0,255,0]);
  const name=String(d.name), safeName=esc(name), quotedName=jsq(name);
  let cams='';for(let i=1;i<=16;i++) cams+=`<option value="${i}" ${Number(d.camera)===i?'selected':''}>CAM ${i}</option>`;
  const rssiText=online?`${d.rssi??'-'} dBm`:'--';
  return `<div class="card"><div class="top"><div><div class="name">${safeName}</div><div class="meta">${esc(d.ip||'-')} · RSSI ${rssiText}</div></div><div class="${online?'online':'offline'}">● ${online?'CONNECTÉ':'HORS LIGNE'}</div></div><div class="meta">État : <span class="state ${stateClass}">${esc((d.state||'off').toUpperCase())}</span></div><div class="grid"><div><label>Caméra attribuée</label><select id="cam-${safeName}" onchange='saveSettings(${quotedName})' ${disabled}>${cams}</select></div><div><label>Couleur PROGRAM</label><input type="color" id="pgm-${safeName}" value="${pgm}" onchange='saveSettings(${quotedName})' ${disabled}></div><div><label>Luminosité : <span id="bv-${safeName}">${d.brightness??100}%</span></label><input type="range" min="1" max="100" value="${d.brightness??100}" id="b-${safeName}" onpointerdown='editingBrightness[${quotedName}]=true' onpointerup='editingBrightness[${quotedName}]=false' onpointercancel='editingBrightness[${quotedName}]=false' oninput='sendBrightness(${quotedName},this.value)' ${disabled}></div><div><label>Couleur PREVIEW</label><input type="color" id="prev-${safeName}" value="${prev}" onchange='saveSettings(${quotedName})' ${disabled}></div></div><div class="actions"><button class="ident" ${disabled} onclick='api(${quotedName},"identify")'>IDENTIFY</button><button class="reboot" ${disabled} onclick='if(confirm("Redémarrer "+${quotedName}+" ?")) api(${quotedName},"reboot")'>REBOOT</button></div><details class="config" data-tally="${safeName}"><summary>CONFIGURATION DU BOÎTIER</summary><div class="config-grid"><div><label>Nom / cadreur</label><input type="text" id="new-name-${safeName}" maxlength="31" value="${safeName}" ${disabled}></div><div><label>Adresse IP fixe</label><input type="text" id="new-ip-${safeName}" inputmode="decimal" value="${esc(d.ip||'192.168.1.81')}" ${disabled}></div><button class="save" ${disabled} onclick='saveNetwork(${quotedName})'>ENREGISTRER</button></div></details></div>`;
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

def esp_get(ip, path, timeout=1.0):
    with urllib.request.urlopen(f"http://{ip}{path}", timeout=timeout) as response:
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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/mobile", "/mobile/"):
            self.send_text(200, PAGE, "text/html")
            return
        if parsed.path == "/devices":
            now = time.time()
            with devices_lock:
                result = []
                for name, device in sorted(devices.items()):
                    item = dict(device)
                    item["online"] = (now - item.get("last_seen", 0)) <= OFFLINE_AFTER
                    result.append(item)
            self.send_text(200, json.dumps(result), "application/json")
            return
        if parsed.path == "/api":
            q = urllib.parse.parse_qs(parsed.query)
            name, action = q.get("name", [""])[0], q.get("action", [""])[0]
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
                        pass
                elif action == "config":
                    new_name = q.get("new_name", [""])[0].strip()
                    new_ip = q.get("new_ip", [""])[0].strip()
                    tricaster = q.get("tricaster", ["192.168.1.50"])[0].strip()
                    if not new_name or len(new_name) > 31:
                        raise ValueError("nom invalide (1 à 31 caractères)")
                    try:
                        socket.inet_aton(new_ip)
                        socket.inet_aton(tricaster)
                    except OSError:
                        raise ValueError("adresse IP invalide")
                    params = {"name": new_name, "ip": new_ip, "tricaster": tricaster}
                    esp_get(ip, "/config?" + urllib.parse.urlencode(params), timeout=2.0)
                    with devices_lock:
                        if name in devices:
                            updated = devices.pop(name)
                            updated["name"] = new_name
                            updated["ip"] = new_ip
                            updated["last_seen"] = 0
                            devices[new_name] = updated
                elif action == "save":
                    camera = max(1, min(16, int(q.get("camera", ["1"])[0])))
                    pgm = hex_to_rgb(q.get("pgm", ["#ff0000"])[0])
                    prev = hex_to_rgb(q.get("preview", ["#00ff00"])[0])
                    esp_get(ip, "/camera?" + urllib.parse.urlencode({"value": camera}))
                    params = {"pr": pgm[0], "pg": pgm[1], "pb": pgm[2], "vr": prev[0], "vg": prev[1], "vb": prev[2]}
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
    threading.Thread(target=udp_listener, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    local_ip = get_local_ip()
    print()
    print("====================================")
    print("   TRICASTER ELITE 2 TALLY MANAGER FINAL V2")
    print("====================================")
    print(f"PC local          : http://127.0.0.1:{HTTP_PORT}")
    print(f"TÉLÉPHONE (Wi-Fi) : http://{local_ip}:{HTTP_PORT}/mobile")
    print("Le téléphone et le PC doivent être sur le même réseau.")
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
