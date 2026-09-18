"""TriCaster Elite 2 Tally Manager - production V4.1.

Adds production pre-flight checks, production lock, verified staged OTA
deployments and persistent incident/event logging.
"""

import base64
import csv
import hmac
import io
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

MANAGER_VERSION = "4.1.0"
HTTP_PORT = 8099
UDP_PORT = 4210
OFFLINE_AFTER = 3.5
MAX_OTA_SIZE = 4 * 1024 * 1024
OTA_VERIFY_TIMEOUT = 50.0
PREFLIGHT_RSSI_WARN = -72
PREFLIGHT_RSSI_FAIL = -80
PREFLIGHT_LATENCY_WARN = 250
PREFLIGHT_LATENCY_FAIL = 1000

APP_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
CONFIG_FILE = APP_DIR / "tally_manager_config.json"
EVENT_LOG_FILE = APP_DIR / "tally_manager_events.csv"

devices = {}
devices_lock = threading.Lock()
config_lock = threading.Lock()
event_log_lock = threading.Lock()

manager_config = {
    "api_token": "CHANGE_ME",
    "ap_aliases": {},
    "production_mode": False,
    "expected_tally_count": 0
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
        manager_config["production_mode"] = bool(manager_config.get("production_mode", False))
        try:
            manager_config["expected_tally_count"] = max(0, int(manager_config.get("expected_tally_count", 0)))
        except (TypeError, ValueError):
            manager_config["expected_tally_count"] = 0
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


def is_production_mode():
    with config_lock:
        return bool(manager_config.get("production_mode", False))


def set_production_mode(enabled):
    with config_lock:
        manager_config["production_mode"] = bool(enabled)
    save_manager_config()
    log_event(
        "PRODUCTION_LOCK",
        details="ACTIVE" if enabled else "DESACTIVE",
        level="WARNING" if enabled else "INFO"
    )


def log_event(event_type, tally="", details="", level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, str(level), str(event_type), str(tally), str(details)]
    with event_log_lock:
        new_file = not EVENT_LOG_FILE.exists()
        with EVENT_LOG_FILE.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(["timestamp", "level", "event", "tally", "details"])
            writer.writerow(row)
    print(f"[{level}] {event_type}" + (f" {tally}" if tally else "") + (f" - {details}" if details else ""))


def read_events(limit=200):
    if not EVENT_LOG_FILE.exists():
        return []
    with event_log_lock:
        try:
            with EVENT_LOG_FILE.open("r", newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        except Exception:
            return []
    if limit > 0:
        rows = rows[-limit:]
    return list(reversed(rows))


def device_online(device, now=None):
    now = time.time() if now is None else now
    return bool(device.get("last_seen")) and (now - float(device.get("last_seen", 0))) <= OFFLINE_AFTER


def preflight_report():
    now = time.time()
    with devices_lock:
        snapshot = {name: dict(device) for name, device in devices.items()}

    checks = []
    errors = 0
    warnings = 0

    def add(level, title, detail):
        nonlocal errors, warnings
        if level == "ERROR":
            errors += 1
        elif level == "WARNING":
            warnings += 1
        checks.append({"level": level, "title": title, "detail": detail})

    if not snapshot:
        add("ERROR", "Aucun tally", "Aucun boitier n'a ete detecte par le Manager.")
    else:
        online = {name: d for name, d in snapshot.items() if device_online(d, now)}
        offline = sorted(set(snapshot) - set(online))

        with config_lock:
            expected_count = int(manager_config.get("expected_tally_count", 0) or 0)
        if expected_count > 0:
            if len(online) < expected_count:
                add("ERROR", "Nombre de tally insuffisant", f"{len(online)}/{expected_count} en ligne")
            elif len(online) > expected_count:
                add("WARNING", "Plus de tally que prevu", f"{len(online)}/{expected_count} en ligne")
            else:
                add("OK", "Nombre de tally attendu", f"{len(online)}/{expected_count}")

        if offline:
            add("ERROR", "Tally hors ligne", ", ".join(offline))
        else:
            add("OK", "Tous les tally detectes sont en ligne", f"{len(online)}/{len(snapshot)}")

        ips = {}
        cameras = {}
        firmwares = {}
        tricaster_ips = {}

        for name, device in sorted(online.items()):
            ip = str(device.get("ip") or "")
            if ip:
                ips.setdefault(ip, []).append(name)

            camera = int(device.get("camera") or 0)
            if camera:
                cameras.setdefault(camera, []).append(name)

            firmware = str(device.get("firmware") or "?")
            firmwares.setdefault(firmware, []).append(name)

            tricaster = str(device.get("tricaster") or "")
            if tricaster:
                tricaster_ips.setdefault(tricaster, []).append(name)

            rssi = int(device.get("rssi") or -100)
            if rssi < PREFLIGHT_RSSI_FAIL:
                add("ERROR", f"{name} RSSI critique", f"{rssi} dBm")
            elif rssi < PREFLIGHT_RSSI_WARN:
                add("WARNING", f"{name} RSSI faible", f"{rssi} dBm")

            latency = int(device.get("tricaster_latency_ms") or 0)
            if latency >= PREFLIGHT_LATENCY_FAIL:
                add("ERROR", f"{name} latence TriCaster critique", f"{latency} ms")
            elif latency >= PREFLIGHT_LATENCY_WARN:
                add("WARNING", f"{name} latence TriCaster elevee", f"{latency} ms")

            if str(device.get("wifi_state") or "") not in ("connected",):
                add("WARNING", f"{name} etat Wi-Fi", str(device.get("wifi_state") or "inconnu"))

            if str(device.get("state") or "") == "error":
                add("ERROR", f"{name} ne recoit plus le TriCaster", "Etat tally ERROR")

            tally_age = int(device.get("last_tally_age_ms") or 0)
            if tally_age > 2500:
                add("ERROR", f"{name} donnees tally trop anciennes", f"{tally_age} ms")

            if not str(device.get("bssid") or ""):
                add("WARNING", f"{name} BSSID absent", "Impossible d'identifier le point d'acces.")

            channel = int(device.get("channel") or 0)
            if channel and channel not in (1, 6, 11):
                add("WARNING", f"{name} canal 2,4 GHz", f"Canal {channel}; 1/6/11 recommandes en 20 MHz.")

        duplicate_ips = {ip: names for ip, names in ips.items() if len(names) > 1}
        if duplicate_ips:
            for ip, names in duplicate_ips.items():
                add("ERROR", "Doublon IP", f"{ip}: {', '.join(names)}")
        elif online:
            add("OK", "Adresses IP uniques", f"{len(ips)} IP controlees")

        duplicate_cameras = {cam: names for cam, names in cameras.items() if len(names) > 1}
        if duplicate_cameras:
            for cam, names in duplicate_cameras.items():
                add("ERROR", "Doublon camera", f"CAM {cam}: {', '.join(names)}")
        elif online:
            add("OK", "Affectations camera uniques", f"{len(cameras)} cameras controlees")

        if len(firmwares) > 1:
            add("WARNING", "Versions firmware differentes", " | ".join(f"{fw}: {', '.join(names)}" for fw, names in firmwares.items()))
        elif online:
            add("OK", "Firmware homogene", next(iter(firmwares.keys()), "?"))

        if len(tricaster_ips) > 1:
            add("ERROR", "IP TriCaster incoherentes", " | ".join(f"{ip}: {', '.join(names)}" for ip, names in tricaster_ips.items()))
        elif online:
            add("OK", "IP TriCaster coherente", next(iter(tricaster_ips.keys()), "?"))

    if current_token() == "CHANGE_ME":
        add("WARNING", "Token administrateur par defaut", "CHANGE_ME doit etre remplace sur un reseau partage.")

    verdict = "NO-GO" if errors else ("ATTENTION" if warnings else "GO")
    report = {
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "production_mode": is_production_mode(),
        "manager_version": MANAGER_VERSION,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    log_event("PREFLIGHT", details=f"{verdict} - {errors} erreur(s), {warnings} avertissement(s)",
              level="ERROR" if errors else ("WARNING" if warnings else "INFO"))
    return report


def wait_for_ota_recovery(name, old_uptime, started_at, timeout=OTA_VERIFY_TIMEOUT):
    deadline = time.time() + timeout
    last_error = "aucune reponse"

    while time.time() < deadline:
        with devices_lock:
            device = dict(devices.get(name, {}))

        ip = str(device.get("ip") or "")
        if ip:
            try:
                info = json.loads(esp_get(ip, "/status", timeout=1.2))
                new_uptime = int(info.get("uptime_ms") or 0)
                reboot_seen = (
                    (old_uptime and new_uptime < old_uptime)
                    or (not old_uptime and time.time() - started_at >= 4.0)
                )
                healthy = (
                    str(info.get("wifi_state") or "") == "connected"
                    and str(info.get("state") or "") != "error"
                    and int(info.get("last_tally_age_ms") or 999999) <= 2500
                )
                if reboot_seen and healthy:
                    with devices_lock:
                        if name in devices:
                            devices[name].update(info)
                            devices[name]["last_seen"] = time.time()
                    return True, f"OK - FW {info.get('firmware', '?')} - TriCaster {info.get('tricaster_latency_ms', '?')} ms"
                if reboot_seen and not healthy:
                    last_error = "ESP revenu mais pas encore sain"
            except Exception as error:
                last_error = str(error)
        time.sleep(1.0)

    return False, f"verification timeout ({last_error})"

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#111111">
<title>TriCaster Elite 2 Tally Manager V4.1</title>
<style>
*{box-sizing:border-box} html{-webkit-text-size-adjust:100%}
body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:0;padding:12px;min-height:100vh}
.wrap{max-width:1500px;margin:auto}.header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:10px}
h1{margin:0;font-size:clamp(21px,3vw,29px)}.sub{color:#aaa;font-size:13px;margin-top:3px}
.access{background:#17251b;border:1px solid #315d3a;border-radius:9px;padding:8px 11px;color:#ccebd2;font-size:12px;max-width:430px}
.access strong{display:inline;margin-right:6px}.access-url{color:#7ee397;overflow-wrap:anywhere}
.panel,.tools{background:#181818;border:1px solid #333;border-radius:10px;padding:10px;margin-bottom:10px}
.safety{display:grid;grid-template-columns:1.5fr auto auto auto;gap:8px;align-items:center}
.tools{display:grid;grid-template-columns:1.3fr 1fr auto auto;gap:10px;align-items:center}
button{border:0;border-radius:7px;padding:7px 8px;min-height:34px;font-size:11px;font-weight:700;cursor:pointer;touch-action:manipulation}
button:disabled{opacity:.45;cursor:not-allowed}.save{background:#2775c9;color:#fff}.ident{background:#7048bd;color:#fff}.reboot{background:#e29122;color:#111}
.lock-off{background:#2775c9;color:#fff}.lock-on{background:#d83e3e;color:#fff}.preflight{background:#267a43;color:#fff}.logsbtn{background:#555;color:#fff}
input[type=number],select,input[type=text],input[type=password]{background:#151515;color:#eee;border:1px solid #444;border-radius:7px;padding:7px;font-size:14px}
input[type=number]{width:90px}select,input[type=range],input[type=color],input[type=text],input[type=password]{width:100%}
input[type=color]{height:34px;background:#151515;border:1px solid #444;border-radius:7px;padding:2px}input[type=range]{min-height:30px}
#list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.card{background:#202020;border:1px solid #333;border-radius:10px;padding:11px;min-width:0}
.top{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.name{font-size:17px;font-weight:700}.online{color:#4bd36b}.offline{color:#e35555}
.meta{color:#aaa;font-size:12px;margin-top:3px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:9px;align-items:end}
label{display:block;color:#bbb;font-size:11px;margin-bottom:3px}.actions{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:9px}
.config{margin-top:8px;border-top:1px solid #383838;padding-top:7px}.config summary{cursor:pointer;color:#aaa;font-size:12px;font-weight:700}
.config-grid{display:grid;grid-template-columns:1fr 1fr auto;gap:7px;align-items:end;margin-top:7px}.state{font-weight:700}.program{color:#ff5757}.preview{color:#4bd36b}.error{color:#f0a020}.idle{color:#aaa}
.rssi-good{color:#58d67b}.rssi-warn{color:#f0b84d}.rssi-bad{color:#ff6666}.diag{margin-top:5px;line-height:1.45}.empty{padding:30px;text-align:center;color:#888;grid-column:1/-1}
.verdict{font-size:20px;font-weight:800;margin-bottom:8px}.go{color:#58d67b}.attention{color:#f0b84d}.nogo{color:#ff6666}
.check{padding:5px 0;border-bottom:1px solid #292929;font-size:12px}.check-ok{color:#8bdd9d}.check-warning{color:#f0c263}.check-error{color:#ff7777}
#preflightPanel,#logsPanel{display:none}.logrow{display:grid;grid-template-columns:150px 70px 145px 100px 1fr;gap:8px;padding:5px 0;border-bottom:1px solid #292929;font-size:11px}
.ota-pick{display:flex;align-items:center;gap:7px;margin-top:8px;font-size:11px;color:#bbb}
.lockbanner{font-weight:800}.locked-card{border-color:#623838}
@media(max-width:750px){body{padding:8px}.header{display:block}.access{margin-top:7px;max-width:none}.safety,.tools{grid-template-columns:1fr}.grid{gap:6px}#list{grid-template-columns:1fr}.config-grid{grid-template-columns:1fr 1fr}.config-grid button{grid-column:1/-1}.actions{grid-template-columns:1fr 1fr}.logrow{grid-template-columns:1fr}.logrow span{display:block}}
</style>
</head>
<body>
<div class="wrap">
<div class="header"><div><h1>TriCaster Elite 2 Tally Manager</h1><div class="sub">Version V4.1 — PRE-FLIGHT · PRODUCTION LOCK · OTA vérifiée · logs persistants</div></div>
<div class="access"><strong>Accès téléphone :</strong><span class="access-url" id="access-url"></span></div></div>

<div class="panel safety">
  <div><span class="lockbanner" id="lockLabel">MODE CONFIGURATION</span><div class="sub" id="lockHelp">Les commandes d'administration sont disponibles.</div></div>
  <div><label>Tally attendus</label><input id="expectedCount" type="number" min="0" max="64" value="0"></div>
  <button class="preflight" onclick="runPreflight()">CHECK PRODUCTION</button>
  <button id="lockButton" class="lock-off" onclick="toggleProduction()">VERROUILLER PRODUCTION</button>
</div>

<div id="preflightPanel" class="panel"></div>

<div class="tools">
  <div><strong>Firmware OTA sécurisé</strong><div class="sub">Chaque boîtier est mis à jour, redémarré puis vérifié avant de passer au suivant. Arrêt au premier échec.</div></div>
  <input type="file" id="firmwareFile" accept=".bin,application/octet-stream">
  <button class="save" id="otaSelected" onclick="uploadFirmware('selected')">MAJ SÉLECTION</button>
  <button class="reboot" id="otaAll" onclick="uploadFirmware('all')">MAJ TOUS</button>
  <span id="otaStatus" class="sub"></span>
</div>

<div class="panel">
  <button class="logsbtn" onclick="toggleLogs()">JOURNAL INCIDENTS</button>
  <a href="/logs.csv" style="margin-left:8px;color:#8fc3ff;font-size:12px">Exporter CSV</a>
  <span class="sub" style="margin-left:8px">Wi-Fi · TriCaster · roaming · reboot · OTA · actions opérateur</span>
</div>
<div id="logsPanel" class="panel"></div>

<div id="list"><div class="empty">Recherche des tally…</div></div>
</div>

<script>
let editingBrightness={};
let brightnessTimers={};
let otaSelection=new Set();
let productionMode=false;
let managerState={};
let logsVisible=false;
document.getElementById('access-url').textContent=window.location.origin+'/mobile';

function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function jsq(s){return JSON.stringify(String(s))}
function rgbHex(v){if(!Array.isArray(v))return'#000000';return'#'+v.map(x=>Math.max(0,Math.min(255,Number(x)||0)).toString(16).padStart(2,'0')).join('')}
function humanMs(ms){ms=Number(ms)||0;if(ms<1000)return ms+' ms';let s=Math.floor(ms/1000);if(s<60)return s+' s';let m=Math.floor(s/60);if(m<60)return m+' min';let h=Math.floor(m/60);if(h<48)return h+' h';return Math.floor(h/24)+' j'}
function rssiClass(v){v=Number(v);if(v>=-65)return'rssi-good';if(v>=-72)return'rssi-warn';return'rssi-bad'}

async function api(name,action,params={}){
  const q=new URLSearchParams({name:name||'',action,...params});
  const r=await fetch('/api?'+q.toString(),{cache:'no-store'});
  const text=await r.text();
  if(!r.ok){alert(text);throw new Error(text)}
  return text;
}

async function refreshManagerState(){
  try{
    const r=await fetch('/manager-state',{cache:'no-store'}),s=await r.json();
    managerState=s;productionMode=!!s.production_mode;
    document.getElementById('expectedCount').value=s.expected_tally_count??0;
    const b=document.getElementById('lockButton'),label=document.getElementById('lockLabel'),help=document.getElementById('lockHelp');
    if(productionMode){
      b.textContent='DÉVERROUILLER';b.className='lock-on';label.textContent='🔒 MODE PRODUCTION ACTIF';
      help.textContent='OTA, reboot, Identify, affectations, couleurs et configuration réseau sont bloqués.';
    }else{
      b.textContent='VERROUILLER PRODUCTION';b.className='lock-off';label.textContent='MODE CONFIGURATION';
      help.textContent='Les commandes d’administration sont disponibles.';
    }
    document.getElementById('otaSelected').disabled=productionMode;
    document.getElementById('otaAll').disabled=productionMode;
  }catch(e){}
}

async function toggleProduction(){
  const enable=!productionMode;
  const msg=enable?'Activer le MODE PRODUCTION ? Les commandes dangereuses seront bloquées.':'DÉVERROUILLER le système et réautoriser les modifications ?';
  if(!confirm(msg))return;
  await api('','production_mode',{value:enable?'1':'0'});
  await refreshManagerState();await refresh();
}

async function saveExpected(){
  const value=document.getElementById('expectedCount').value||'0';
  await api('','expected_count',{value});
}

document.getElementById('expectedCount').addEventListener('change',saveExpected);

async function runPreflight(){
  const panel=document.getElementById('preflightPanel');panel.style.display='block';panel.innerHTML='Contrôle en cours…';
  try{
    const r=await fetch('/preflight',{cache:'no-store'}),p=await r.json();
    const klass=p.verdict==='GO'?'go':p.verdict==='NO-GO'?'nogo':'attention';
    panel.innerHTML='<div class="verdict '+klass+'">'+esc(p.verdict)+'</div><div class="sub">'+esc(p.timestamp)+' · '+p.errors+' erreur(s) · '+p.warnings+' avertissement(s)</div>'+
      p.checks.map(x=>'<div class="check check-'+x.level.toLowerCase()+'"><strong>'+esc(x.level)+'</strong> — '+esc(x.title)+' : '+esc(x.detail)+'</div>').join('');
  }catch(e){panel.innerHTML='<div class="verdict nogo">ERREUR PRE-FLIGHT</div>'+esc(e)}
}

function otaToggle(name,checked){if(checked)otaSelection.add(name);else otaSelection.delete(name)}

async function uploadFirmware(mode,singleName=''){
  if(productionMode)return alert('Mode Production actif : OTA bloquée.');
  const input=document.getElementById('firmwareFile'),status=document.getElementById('otaStatus');
  const file=input.files&&input.files[0];if(!file)return alert('Sélectionne un fichier .bin.');
  let targets='';
  if(mode==='single')targets=singleName;
  else if(mode==='selected'){targets=[...otaSelection].join(',');if(!targets)return alert('Sélectionne au moins un tally.');}
  const label=mode==='all'?'TOUS les tally en ligne':(mode==='single'?singleName:targets);
  if(!confirm('Lancer l’OTA vérifiée sur '+label+' ? Le déploiement s’arrête au premier échec.'))return;
  status.textContent='OTA en cours : ne ferme pas cette page…';
  try{
    const q=new URLSearchParams();if(targets)q.set('targets',targets);q.set('stop_on_failure','1');
    const r=await fetch('/ota-upload?'+q.toString(),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':file.name},body:file});
    const data=await r.json();
    status.textContent=data.message||'OTA terminée';
    if(!r.ok||data.failures?.length)alert((data.message||'OTA')+'\n'+(data.failures||[]).join('\n'));
    await refresh();
  }catch(e){status.textContent='Erreur OTA : '+e;alert(status.textContent)}
}

async function saveSettings(name){
  const cam=document.getElementById('cam-'+name),pgm=document.getElementById('pgm-'+name),prev=document.getElementById('prev-'+name);
  if(cam&&pgm&&prev)await api(name,'save',{camera:cam.value,pgm:pgm.value,preview:prev.value});
}
function sendBrightness(name,value){const o=document.getElementById('bv-'+name);if(o)o.textContent=value+'%';clearTimeout(brightnessTimers[name]);brightnessTimers[name]=setTimeout(()=>api(name,'brightness',{value}).catch(()=>{}),100)}
async function saveNetwork(oldName){
  const g=id=>document.getElementById(id+'-'+oldName);
  const newName=g('new-name').value.trim(),dhcp=g('dhcp').checked?'1':'0';
  const params={new_name:newName,dhcp,ssid:g('ssid').value.trim(),wifi_password:g('wifi-pass').value,new_ip:g('new-ip').value.trim(),gateway:g('gateway').value.trim(),subnet:g('subnet').value.trim(),dns:g('dns').value.trim(),tricaster:g('tricaster').value.trim()};
  if(!newName)return alert('Le nom est obligatoire.');
  if(!confirm('Appliquer la configuration réseau à '+oldName+' ? Le tally va redémarrer.'))return;
  await api(oldName,'config',params);
}
async function saveApAlias(name){const i=document.getElementById('ap-alias-'+name);if(i)await api(name,'ap_alias',{alias:i.value.trim()})}

async function toggleLogs(){logsVisible=!logsVisible;document.getElementById('logsPanel').style.display=logsVisible?'block':'none';if(logsVisible)await refreshLogs()}
async function refreshLogs(){
  if(!logsVisible)return;
  try{
    const r=await fetch('/logs?limit=150',{cache:'no-store'}),rows=await r.json();
    document.getElementById('logsPanel').innerHTML=rows.length?rows.map(x=>'<div class="logrow"><span>'+esc(x.timestamp)+'</span><span>'+esc(x.level)+'</span><span>'+esc(x.event)+'</span><span>'+esc(x.tally)+'</span><span>'+esc(x.details)+'</span></div>').join(''):'<div class="sub">Aucun événement enregistré.</div>';
  }catch(e){}
}

function card(d){
  const online=d.online;
  const adminDisabled=(online&&!productionMode)?'':'disabled';
  const onlineDisabled=online?'':'disabled';
  const stateClass=d.state==='program'?'program':d.state==='preview'?'preview':d.state==='error'?'error':'idle';
  const pgm=rgbHex(d.pgm||[255,0,0]),prev=rgbHex(d.preview||[0,255,0]);
  const name=String(d.name),safeName=esc(name),quotedName=jsq(name);
  let cams='';for(let i=1;i<=32;i++)cams+='<option value="'+i+'" '+(Number(d.camera)===i?'selected':'')+'>CAM '+i+'</option>';
  const rssi=Number(d.rssi??-100),rssiText=online?rssi+' dBm':'--';
  const channelText=online&&d.channel?'CH '+d.channel:'CH --';
  const bssidText=online&&d.bssid?String(d.bssid):'--:--:--:--:--:--';
  const apLabel=d.ap_name||bssidText;
  const wifiLabels={connected:'Wi-Fi OK',roaming:'ROAMING',searching:'RECHERCHE Wi-Fi',connecting:'CONNEXION Wi-Fi'};
  const wifiText=wifiLabels[d.wifi_state]||String(d.wifi_state||'Wi-Fi OK');
  const latency=d.tricaster_latency_ms??'-',uptime=humanMs(d.uptime_ms),tallyAge=humanMs(d.last_tally_age_ms),roamAge=Number(d.last_roam_age_ms||0)>0?humanMs(d.last_roam_age_ms):'jamais';
  const losses='Wi-Fi '+(d.wifi_loss_count??0)+' · TriCaster '+(d.tricaster_loss_count??0)+' · roam '+(d.roam_count??0);
  const checked=otaSelection.has(name)?'checked':'';
  return '<div class="card '+(productionMode?'locked-card':'')+'">'+
    '<div class="top"><div><div class="name">'+safeName+'</div>'+
    '<div class="meta">'+esc(d.ip||'-')+' · <span class="'+rssiClass(rssi)+'">RSSI '+rssiText+'</span> · '+esc(channelText)+'</div>'+
    '<div class="meta">AP : '+esc(apLabel)+(d.ap_name?' · '+esc(bssidText):'')+' · '+esc(wifiText)+'</div>'+
    '<div class="meta diag">FW '+esc(d.firmware||'?')+' · TriCaster '+esc(String(latency))+' ms · dernière trame '+esc(tallyAge)+' · uptime '+esc(uptime)+'</div>'+
    '<div class="meta diag">Pertes : '+esc(losses)+' · dernier roaming : '+esc(roamAge)+'</div></div>'+
    '<div class="'+(online?'online':'offline')+'">● '+(online?'CONNECTÉ':'HORS LIGNE')+'</div></div>'+
    '<div class="meta">État : <span class="state '+stateClass+'">'+esc((d.state||'off').toUpperCase())+'</span></div>'+
    '<div class="ota-pick"><input type="checkbox" '+checked+' '+(productionMode||!online?'disabled':'')+' onchange="otaToggle('+quotedName+',this.checked)"> Inclure dans la MAJ sélectionnée</div>'+
    '<div class="grid">'+
      '<div><label>Caméra attribuée</label><select id="cam-'+safeName+'" onchange="saveSettings('+quotedName+')" '+adminDisabled+'>'+cams+'</select></div>'+
      '<div><label>Couleur PROGRAM</label><input type="color" id="pgm-'+safeName+'" value="'+pgm+'" onchange="saveSettings('+quotedName+')" '+adminDisabled+'></div>'+
      '<div><label>Luminosité : <span id="bv-'+safeName+'">'+(d.brightness??100)+'%</span></label><input type="range" min="1" max="100" value="'+(d.brightness??100)+'" id="b-'+safeName+'" onpointerdown="editingBrightness['+quotedName+']=true" onpointerup="editingBrightness['+quotedName+']=false" oninput="sendBrightness('+quotedName+',this.value)" '+adminDisabled+'></div>'+
      '<div><label>Couleur PREVIEW</label><input type="color" id="prev-'+safeName+'" value="'+prev+'" onchange="saveSettings('+quotedName+')" '+adminDisabled+'></div>'+
    '</div>'+
    '<div class="actions"><button class="ident" '+adminDisabled+' onclick="api('+quotedName+',\'identify\')">IDENTIFY</button>'+
    '<button class="reboot" '+adminDisabled+' onclick="if(confirm(\'Redémarrer '+safeName+' ?\'))api('+quotedName+',\'reboot\')">REBOOT</button>'+
    '<button class="save" '+adminDisabled+' onclick="uploadFirmware(\'single\','+quotedName+')">OTA CE TALLY</button></div>'+
    '<details class="config" data-tally="'+safeName+'"><summary>CONFIGURATION RÉSEAU / BOÎTIER</summary><div class="config-grid">'+
      '<div><label>Nom / cadreur</label><input type="text" id="new-name-'+safeName+'" maxlength="31" value="'+safeName+'" '+adminDisabled+'></div>'+
      '<div><label>SSID</label><input type="text" id="ssid-'+safeName+'" maxlength="32" value="'+esc(d.ssid||'')+'" '+adminDisabled+'></div>'+
      '<div><label>Mot de passe Wi-Fi (vide = inchangé)</label><input type="password" id="wifi-pass-'+safeName+'" maxlength="64" '+adminDisabled+'></div>'+
      '<div><label>TriCaster</label><input type="text" id="tricaster-'+safeName+'" value="'+esc(d.tricaster||'192.168.1.50')+'" '+adminDisabled+'></div>'+
      '<div><label><input type="checkbox" id="dhcp-'+safeName+'" '+(d.dhcp?'checked':'')+' '+adminDisabled+'> DHCP</label></div>'+
      '<div><label>Adresse IP fixe</label><input type="text" id="new-ip-'+safeName+'" value="'+esc(d.ip||'192.168.1.81')+'" '+adminDisabled+'></div>'+
      '<div><label>Gateway</label><input type="text" id="gateway-'+safeName+'" value="'+esc(d.gateway||'192.168.1.1')+'" '+adminDisabled+'></div>'+
      '<div><label>Subnet</label><input type="text" id="subnet-'+safeName+'" value="'+esc(d.subnet||'255.255.255.0')+'" '+adminDisabled+'></div>'+
      '<div><label>DNS</label><input type="text" id="dns-'+safeName+'" value="'+esc(d.dns||d.gateway||'192.168.1.1')+'" '+adminDisabled+'></div>'+
      '<button class="save" '+adminDisabled+' onclick="saveNetwork('+quotedName+')">ENREGISTRER RÉSEAU</button></div>'+
      '<div class="config-grid"><div><label>Nom convivial de l\'AP actuel</label><input type="text" id="ap-alias-'+safeName+'" value="'+esc(d.ap_name||'')+'" placeholder="ex. AP TERRAIN" '+onlineDisabled+'></div>'+
      '<div><label>BSSID</label><input type="text" value="'+esc(bssidText)+'" disabled></div><button class="save" '+onlineDisabled+' onclick="saveApAlias('+quotedName+')">NOMMER CET AP</button></div>'+
    '</details></div>';
}

async function refresh(){
  try{
    const r=await fetch('/devices',{cache:'no-store'}),ds=await r.json();
    const someoneEditing=Object.values(editingBrightness).some(v=>v===true),active=document.activeElement;
    const controlFocused=active&&(active.tagName==='INPUT'||active.tagName==='SELECT');
    if(someoneEditing||controlFocused)return;
    const openConfigs=new Set([...document.querySelectorAll('details.config[open]')].map(el=>el.dataset.tally).filter(Boolean));
    document.getElementById('list').innerHTML=ds.length?ds.map(card).join(''):'<div class="empty">Aucun tally détecté.</div>';
    document.querySelectorAll('details.config').forEach(el=>{if(openConfigs.has(el.dataset.tally))el.open=true});
  }catch(e){}
}

async function tick(){await refreshManagerState();await refresh();await refreshLogs()}
tick();setInterval(tick,1000);
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

            now = time.time()
            msg["ip"] = msg.get("ip") or addr[0]
            msg["last_seen"] = now

            with devices_lock:
                first_seen = name not in devices
                old = dict(devices.get(name, {}))

                recovered = bool(old.get("_offline_logged"))
                old_bssid = str(old.get("bssid") or "")
                new_bssid = str(msg.get("bssid") or "")
                old_fw = str(old.get("firmware") or "")
                new_fw = str(msg.get("firmware") or "")
                old_wifi_loss = int(old.get("wifi_loss_count") or 0)
                new_wifi_loss = int(msg.get("wifi_loss_count") or 0)
                old_tc_loss = int(old.get("tricaster_loss_count") or 0)
                new_tc_loss = int(msg.get("tricaster_loss_count") or 0)
                old_state = str(old.get("state") or "")
                new_state = str(msg.get("state") or "")

                merged = old
                merged.update(msg)
                merged["_offline_logged"] = False
                devices[name] = merged

            if first_seen:
                log_event("DEVICE_DISCOVERED", name, f"{msg['ip']} - FW {msg.get('firmware', '?')}")
                threading.Thread(target=refresh_device_details, args=(msg["ip"], name), daemon=True).start()
            elif recovered:
                log_event("DEVICE_RECOVERED", name, f"{msg['ip']}")

            if old_bssid and new_bssid and old_bssid != new_bssid:
                log_event("ROAM", name, f"{old_bssid} -> {new_bssid} / CH {msg.get('channel', '?')}")

            if old_fw and new_fw and old_fw != new_fw:
                log_event("FIRMWARE_CHANGED", name, f"{old_fw} -> {new_fw}")

            if new_wifi_loss > old_wifi_loss:
                log_event("WIFI_LOSS", name, f"compteur {old_wifi_loss} -> {new_wifi_loss}", "WARNING")

            if new_tc_loss > old_tc_loss:
                log_event("TRICASTER_LOSS", name, f"compteur {old_tc_loss} -> {new_tc_loss}", "WARNING")

            if new_state == "error" and old_state != "error":
                log_event("TALLY_ERROR", name, "Communication TriCaster perdue", "ERROR")
            elif old_state == "error" and new_state != "error":
                log_event("TALLY_RECOVERED", name, f"Etat {new_state}")

        except Exception as error:
            print(f"[UDP] trame ignoree: {error}")


def offline_monitor():
    while True:
        now = time.time()
        to_log = []

        with devices_lock:
            for name, device in devices.items():
                last_seen = float(device.get("last_seen", 0) or 0)
                if last_seen and now - last_seen > OFFLINE_AFTER and not device.get("_offline_logged"):
                    device["_offline_logged"] = True
                    to_log.append((name, str(device.get("ip") or "")))

        for name, ip in to_log:
            log_event("DEVICE_OFFLINE", name, ip, "ERROR")

        time.sleep(1.0)

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

    def send_bytes(self, code, body, ctype, filename=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
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

        if parsed.path == "/manager-state":
            with config_lock:
                state = {
                    "manager_version": MANAGER_VERSION,
                    "production_mode": bool(manager_config.get("production_mode", False)),
                    "expected_tally_count": int(manager_config.get("expected_tally_count", 0) or 0)
                }
            self.send_text(200, json.dumps(state, ensure_ascii=False), "application/json")
            return

        if parsed.path == "/preflight":
            self.send_text(200, json.dumps(preflight_report(), ensure_ascii=False), "application/json")
            return

        if parsed.path == "/logs":
            q = urllib.parse.parse_qs(parsed.query)
            try:
                limit = max(1, min(2000, int(q.get("limit", ["200"])[0])))
            except ValueError:
                limit = 200
            self.send_text(200, json.dumps(read_events(limit), ensure_ascii=False), "application/json")
            return

        if parsed.path == "/logs.csv":
            if EVENT_LOG_FILE.exists():
                with event_log_lock:
                    body = EVENT_LOG_FILE.read_bytes()
            else:
                body = b"timestamp,level,event,tally,details\r\n"
            self.send_bytes(200, body, "text/csv; charset=utf-8", "tally_manager_events.csv")
            return

        if parsed.path == "/devices":
            now = time.time()
            with config_lock:
                aliases = dict(manager_config.get("ap_aliases", {}))

            with devices_lock:
                result = []
                for name, device in sorted(devices.items()):
                    item = {k: v for k, v in device.items() if not str(k).startswith("_")}
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

            if action == "production_mode":
                enabled = q.get("value", ["0"])[0] == "1"
                set_production_mode(enabled)
                self.send_text(200, "OK", "text/plain")
                return

            if action == "expected_count":
                try:
                    value = max(0, min(64, int(q.get("value", ["0"])[0])))
                except ValueError:
                    self.send_text(400, "Nombre de tally invalide", "text/plain")
                    return
                with config_lock:
                    manager_config["expected_tally_count"] = value
                save_manager_config()
                log_event("EXPECTED_COUNT", details=str(value))
                self.send_text(200, "OK", "text/plain")
                return

            if is_production_mode() and action in {"brightness", "identify", "reboot", "config", "save"}:
                self.send_text(423, "MODE PRODUCTION ACTIF : commande bloquee.", "text/plain")
                return

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
                log_event("AP_ALIAS", name, f"{bssid} = {alias or '(supprime)'}")
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
                    log_event("BRIGHTNESS", name, f"{value}%")

                elif action == "identify":
                    esp_get(ip, "/identify")
                    log_event("IDENTIFY", name)

                elif action == "reboot":
                    log_event("REBOOT_REQUEST", name, ip, "WARNING")
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

                    log_event("CONFIG_CHANGE", name, f"nom={new_name}, dhcp={dhcp}, ip={new_ip or 'DHCP'}, tricaster={tricaster}", "WARNING")
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
                    log_event("TALLY_SETTINGS", name, f"CAM {camera} / PGM {q.get('pgm', [''])[0]} / PREV {q.get('preview', [''])[0]}")
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
