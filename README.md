# TriCaster Elite 2 WiFi Tally

Open-source Wi-Fi tally system for the **NewTek / Vizrt TriCaster Elite 2**, based on inexpensive **ESP8266 NodeMCU** modules.

Each tally unit communicates **directly with the TriCaster Elite 2 over the local network**.  
The optional web Manager is used only for configuration and supervision, so the tally lights continue to work even if the Manager is closed.

---

# Français

## Présentation

Ce projet permet de créer des boîtiers tally Wi-Fi pour **TriCaster Elite 2** à l'aide d'un ESP8266.

Chaque boîtier affiche l'état de la caméra assignée :

- 🔴 **PROGRAM**
- 🟢 **PREVIEW**
- ⚫ **OFF** — ni Program ni Preview
- 🟡 **ERROR** — perte de communication avec le TriCaster
- 🔵 indication réseau / démarrage

Le firmware interroge directement :

```text
http://IP_DU_TRICASTER/v1/dictionary?key=tally
```

Exemple de réponse du TriCaster :

```xml
<column name="input2" index="1" on_pgm="true" on_prev="false" ndi_id="1"/>
```

Le firmware recherche précisément la balise correspondant à `inputX` :

- `on_pgm="true"` → PROGRAM
- `on_prev="true"` → PREVIEW
- les deux à `false` → OFF
- aucune réponse valide pendant environ 2 secondes → ERROR

Le Manager n'est pas indispensable au fonctionnement du tally : les ESP communiquent directement avec le TriCaster Elite 2.

## Matériel nécessaire

Pour chaque tally :

- 1 × **ESP8266 NodeMCU**
- 1 × petit module / ruban **RGB à anode commune**
- configuration testée : **3 LED RGB**
- 1 × alimentation USB 5 V
- fils, soudure et connecteurs
- boîtier, par exemple imprimé en 3D
- accès au même réseau local que le TriCaster Elite 2

Pour l'installation complète :

- 1 × **TriCaster Elite 2**
- 1 × réseau LAN avec Wi-Fi 2,4 GHz
- facultatif : un PC Windows ou le TriCaster lui-même pour exécuter le Manager

> Pour un ruban plus long ou une puissance plus élevée, utilisez des MOSFET/transistors ou un driver LED adapté. Ne faites pas passer une charge importante directement par les sorties de l'ESP8266.

## Câblage

Configuration testée avec ruban RGB **anode commune** :

| ESP8266 | RGB |
|---|---|
| `3V3` | `+` commun |
| `D1` | Vert |
| `D2` | Rouge |
| `D3` | Bleu |

La logique PWM est inversée car il s'agit d'une anode commune.

> Sur beaucoup de cartes NodeMCU, `D3` correspond à GPIO0, qui intervient aussi au démarrage. Si l'ESP refuse de booter avec le ruban connecté, débranchez temporairement cette ligne pendant le flash ou changez le brochage dans le firmware.

## Animation au démarrage

```text
Noir → Rouge → Jaune → Vert → Cyan → Bleu → Magenta → Rouge → Noir
```

puis trois flashs blancs rapides.

## Installation du firmware

1. Installer **Arduino IDE**.
2. Installer **esp8266 by ESP8266 Community**.
3. Sélectionner `NodeMCU 1.0 (ESP-12E Module)`.
4. Ouvrir `TriCaster_Elite2_Tally_ESP8266.ino`.
5. Renseigner le Wi-Fi :

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
```

6. Choisir le numéro du tally :

```cpp
#define DEFAULT_TALLY_NUMBER 1
```

7. Compiler puis téléverser.

Moniteur série : `115200 baud`.

## Choisir l'IP du TriCaster Elite 2

La version publique utilise comme exemple :

```text
TriCaster Elite 2 : 192.168.1.50
Gateway           : 192.168.1.1
Subnet            : 255.255.255.0
```

Dans le firmware, recherchez `setDefaults()` :

```cpp
config.tricaster[0] = 192;
config.tricaster[1] = 168;
config.tricaster[2] = 1;
config.tricaster[3] = 50;
```

Si votre TriCaster est par exemple en `10.20.30.40`, utilisez :

```cpp
config.tricaster[0] = 10;
config.tricaster[1] = 20;
config.tricaster[2] = 30;
config.tricaster[3] = 40;
```

Adaptez également `gateway`, `subnet`, `dns` et `broadcastIP` à votre réseau.

## Choisir les IP des tally

Par défaut :

| Tally | IP |
|---|---|
| TALLY-01 | `192.168.1.81` |
| TALLY-02 | `192.168.1.82` |
| TALLY-03 | `192.168.1.83` |
| TALLY-04 | `192.168.1.84` |
| TALLY-05 | `192.168.1.85` |
| TALLY-06 | `192.168.1.86` |
| TALLY-07 | `192.168.1.87` |
| TALLY-08 | `192.168.1.88` |

La règle est :

```cpp
config.ip[0] = 192;
config.ip[1] = 168;
config.ip[2] = 1;
config.ip[3] = 80 + constrain(DEFAULT_TALLY_NUMBER, 1, 8);
```

Ainsi `#define DEFAULT_TALLY_NUMBER 3` donne `192.168.1.83`.

**Important :** choisissez des IP hors de la plage DHCP de votre routeur, ou créez des réservations DHCP.

## Affectation caméra / entrée

Par défaut :

```cpp
config.camera = constrain(DEFAULT_TALLY_NUMBER, 1, 8);
```

Donc `TALLY-01 → input1`, `TALLY-02 → input2`, etc. L'affectation peut ensuite être modifiée depuis le Manager sans reflasher l'ESP.

## Tally Manager

Fichier : `TriCaster_Elite2_Tally_Manager.py`

Le Manager fournit :

- détection automatique des tally
- état connecté / hors ligne
- adresse IP et RSSI Wi-Fi
- affectation caméra
- réglage couleur PROGRAM / PREVIEW
- luminosité individuelle
- Identify
- reboot distant
- modification du nom et de l'adresse IP
- interface mobile

Ports utilisés :

| Fonction | Port |
|---|---|
| Interface web | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| API HTTP ESP8266 | TCP `80` |

Interface locale : `http://127.0.0.1:8099`

Depuis un téléphone : `http://IP_DU_PC_MANAGER:8099/mobile`

### IP du TriCaster dans le Manager

La version publique utilise `192.168.1.50`. Si votre TriCaster utilise une autre adresse, recherchez `192.168.1.50` dans `TriCaster_Elite2_Tally_Manager.py` et remplacez toutes les occurrences avant de compiler l'EXE.

## Compiler le Manager en EXE

```powershell
py -m pip install pyinstaller
```

Version avec console :

```powershell
py -m PyInstaller --noconfirm --clean --onefile --console --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

Version silencieuse :

```powershell
py -m PyInstaller --noconfirm --clean --onefile --windowed --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

L'exécutable sera dans `dist\TriCaster_Elite2_Tally_Manager.exe`.

## Démarrage automatique sur le TriCaster

Avec Windows Task Scheduler :

```text
Trigger                 : At log on
Run only when logged on : Yes
Run with highest privileges
Action                  : TriCaster_Elite2_Tally_Manager.exe
If already running      : Do not start a new instance
```

---

# English

## Overview

This project provides low-cost Wi-Fi tally units for the **NewTek / Vizrt TriCaster Elite 2** using ESP8266 NodeMCU boards.

Each tally reads the TriCaster tally state directly over the local network and displays:

- 🔴 **PROGRAM**
- 🟢 **PREVIEW**
- ⚫ **OFF**
- 🟡 **ERROR / TriCaster connection lost**
- 🔵 network/startup indication

The ESP8266 queries:

```text
http://TRICASTER_IP/v1/dictionary?key=tally
```

A typical response contains:

```xml
<column name="input2" index="1" on_pgm="true" on_prev="false" ndi_id="1"/>
```

The firmware isolates the exact `inputX` XML element:

- `on_pgm="true"` → PROGRAM
- `on_prev="true"` → PREVIEW
- both `false` → OFF
- no valid response for roughly 2 seconds → ERROR

The optional Manager is not part of the critical tally path. Each ESP communicates directly with the TriCaster Elite 2.

## Required hardware

For each tally:

- 1 × **ESP8266 NodeMCU**
- 1 × small **common-anode RGB LED module/strip**
- tested configuration: **3 RGB LEDs**
- 1 × 5 V USB power supply
- wiring / solder / connectors
- optional 3D-printed enclosure
- access to the same network as the TriCaster Elite 2

Overall system:

- 1 × **TriCaster Elite 2**
- LAN with 2.4 GHz Wi-Fi
- optional Windows computer, or the TriCaster itself, for the Manager

## Wiring

| ESP8266 | RGB |
|---|---|
| `3V3` | Common `+` |
| `D1` | Green |
| `D2` | Red |
| `D3` | Blue |

The firmware uses inverted PWM for a common-anode RGB strip.

## Firmware installation

1. Install Arduino IDE.
2. Install **esp8266 by ESP8266 Community**.
3. Select `NodeMCU 1.0 (ESP-12E Module)`.
4. Open `TriCaster_Elite2_Tally_ESP8266.ino`.
5. Enter your Wi-Fi details.
6. Select the tally number with `#define DEFAULT_TALLY_NUMBER 1`.
7. Compile and upload.

Serial monitor: `115200 baud`.

## Choosing the TriCaster Elite 2 IP

Public example:

```text
TriCaster Elite 2 : 192.168.1.50
Gateway           : 192.168.1.1
Subnet            : 255.255.255.0
```

Replace the firmware `config.tricaster[]` values with the actual TriCaster address and update the gateway, DNS and broadcast address to match your network.

## Choosing tally IP addresses

Default public example:

| Tally | IP |
|---|---|
| TALLY-01 | `192.168.1.81` |
| TALLY-02 | `192.168.1.82` |
| TALLY-03 | `192.168.1.83` |
| TALLY-04 | `192.168.1.84` |
| TALLY-05 | `192.168.1.85` |
| TALLY-06 | `192.168.1.86` |
| TALLY-07 | `192.168.1.87` |
| TALLY-08 | `192.168.1.88` |

Keep these static addresses outside your DHCP pool or reserve them in your router.

## Camera/input assignment

By default `TALLY-01 → input1`, `TALLY-02 → input2`, etc. Assignments can later be changed from the Manager without reflashing the tally.

## Manager

File: `TriCaster_Elite2_Tally_Manager.py`

Features include automatic discovery, online/offline status, IP/RSSI, camera assignment, PROGRAM/PREVIEW colors, brightness, Identify, reboot, device name/IP configuration and a mobile interface.

Ports:

| Function | Port |
|---|---|
| Manager web UI | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| ESP8266 HTTP API | TCP `80` |

Local UI: `http://127.0.0.1:8099`

Mobile/LAN UI: `http://MANAGER_PC_IP:8099/mobile`

The public Manager uses `192.168.1.50` as its example TriCaster IP. Replace all occurrences with your own TriCaster IP before building the EXE.

## Building the Windows Manager

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

## Automatic startup

Recommended Windows Task Scheduler configuration:

```text
Trigger                 : At log on
Run only when logged on : Yes
Run with highest privileges
Action                  : TriCaster_Elite2_Tally_Manager.exe
If already running      : Do not start a new instance
```

## License

MIT License.

## Disclaimer

This is an independent open-source project for use with TriCaster Elite 2 systems.  
NewTek, Vizrt and TriCaster are trademarks of their respective owners. This project is not affiliated with or endorsed by Vizrt or NewTek.