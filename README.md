# TriCaster Elite 2 WiFi Tally

![TriCaster Elite 2 WiFi Tally](assets/tricaster-elite2-wifi-tally-hero.webp)

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

- 1 × **ESP8266 NodeMCU avec USB-C** — modèle utilisé : https://fr.aliexpress.com/item/1005006889833004.html
- 1 × ruban **RGB à anode commune** — modèle utilisé : https://fr.aliexpress.com/item/1005004188897288.html
- **2 LED RGB seulement** sont utilisées dans le boîtier fourni
- 1 × câble **USB-C vers USB-C** pour l'alimentation depuis le port USB-C d'une Sony FX6, ou une alimentation USB-C 5 V classique
- fils, soudure et connecteurs
- 1 × boîtier imprimé en **PLA** à partir du fichier 3D fourni
- 1 × **insert fileté 1/4"** pour fixation sur accessoires caméra — exemple : https://fr.aliexpress.com/item/1005006071559268.html
- accès au même réseau local que le TriCaster Elite 2

Pour l'installation complète :

- 1 × **TriCaster Elite 2**
- 1 × réseau LAN avec Wi-Fi 2,4 GHz
- facultatif : un PC Windows ou le TriCaster lui-même pour exécuter le Manager

> Pour un ruban plus long ou une puissance plus élevée, utilisez des MOSFET/transistors ou un driver LED adapté. Ne faites pas passer une charge importante directement par les sorties de l'ESP8266.

## Boîtier 3D et fixation caméra

Le dépôt inclut le fichier 3D du boîtier :

```text
hardware/TALLY_TRICASTER_v6.3mf
```

Le boîtier est conçu pour être imprimé en **PLA**.

Il prévoit un logement pour un **insert fileté 1/4"**, permettant de fixer directement le tally sur les accessoires de rig caméra courants :

- bras articulé / magic arm
- mini rotule
- adaptateur ou support de griffe flash / cold shoe
- autres accessoires de bijout caméra utilisant une fixation 1/4"

Exemple d'insert utilisé :

https://fr.aliexpress.com/item/1005006071559268.html

Le boîtier a été conçu autour de **2 LED RGB** seulement.

### Alimentation sur caméra

Sur une **Sony FX6**, le tally peut être alimenté directement depuis le port USB-C de la caméra avec un câble **USB-C vers USB-C**.

Si aucun port USB-C caméra n'est disponible, une simple alimentation **5 V USB-C** suffit.

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
3. Sélectionner :
   ```text
   NodeMCU 1.0 (ESP-12E Module)
   ```
4. Ouvrir :
   ```text
   TriCaster_Elite2_Tally_ESP8266.ino
   ```
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

Moniteur série :

```text
115200 baud
```

---

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

Si votre TriCaster est par exemple en :

```text
10.20.30.40
```

utilisez :

```cpp
config.tricaster[0] = 10;
config.tricaster[1] = 20;
config.tricaster[2] = 30;
config.tricaster[3] = 40;
```

Adaptez également :

```cpp
IPAddress gateway(...);
IPAddress subnet(...);
IPAddress dns(...);
IPAddress broadcastIP(...);
```

à votre réseau.

---

## Choisir les IP des tally

Par défaut, le firmware utilise :

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

Ainsi :

```cpp
#define DEFAULT_TALLY_NUMBER 3
```

donne automatiquement :

```text
192.168.1.83
```

Pour utiliser un autre sous-réseau, changez les trois premiers octets.

**Important :** choisissez des IP hors de la plage DHCP de votre routeur, ou créez des réservations DHCP, afin d'éviter les conflits d'adresse.

---

## Affectation caméra / entrée

Par défaut :

```cpp
config.camera = constrain(DEFAULT_TALLY_NUMBER, 1, 8);
```

Donc :

```text
TALLY-01 → input1
TALLY-02 → input2
TALLY-03 → input3
...
```

L'affectation peut ensuite être modifiée depuis le Manager sans reflasher l'ESP.

---

## Tally Manager

Fichier :

```text
TriCaster_Elite2_Tally_Manager.py
```

Le Manager fournit :

- détection automatique des tally
- état connecté / hors ligne
- adresse IP
- RSSI Wi-Fi
- affectation caméra
- réglage couleur PROGRAM
- réglage couleur PREVIEW
- luminosité individuelle
- fonction Identify
- reboot distant
- modification du nom et de l'adresse IP
- interface mobile

Ports utilisés :

| Fonction | Port |
|---|---|
| Interface web | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| API HTTP ESP8266 | TCP `80` |

Interface locale :

```text
http://127.0.0.1:8099
```

Depuis un téléphone sur le même réseau :

```text
http://IP_DU_PC_MANAGER:8099/mobile
```

### IP du TriCaster dans le Manager

La version publique utilise :

```text
192.168.1.50
```

Si votre TriCaster utilise une autre adresse, recherchez :

```text
192.168.1.50
```

dans :

```text
TriCaster_Elite2_Tally_Manager.py
```

et remplacez toutes les occurrences par l'adresse de votre TriCaster avant de compiler l'EXE.

---

## Compiler le Manager en EXE

Installer PyInstaller :

```powershell
py -m pip install pyinstaller
```

Version avec console :

```powershell
py -m PyInstaller --noconfirm --clean --onefile --console --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

Version silencieuse pour fonctionnement en arrière-plan :

```powershell
py -m PyInstaller --noconfirm --clean --onefile --windowed --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

L'exécutable sera dans :

```text
dist\TriCaster_Elite2_Tally_Manager.exe
```

---

## Démarrage automatique sur le TriCaster

Avec le **Task Scheduler** Windows :

```text
Trigger                 : At log on
Run only when logged on : Yes
Run with highest privileges
Action                  : TriCaster_Elite2_Tally_Manager.exe
If already running      : Do not start a new instance
```

Cela fonctionne particulièrement bien sur un TriCaster configuré avec ouverture automatique de session Windows.

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

- 1 × **ESP8266 NodeMCU with USB-C** — board used: https://fr.aliexpress.com/item/1005006889833004.html
- 1 × **common-anode RGB LED strip** — strip used: https://fr.aliexpress.com/item/1005004188897288.html
- the supplied enclosure uses **2 RGB LEDs only**
- 1 × **USB-C to USB-C cable** for power from a Sony FX6 USB-C port, or a standard 5 V USB-C power supply
- wiring / solder / connectors
- 1 × **PLA** 3D-printed enclosure using the supplied model
- 1 × **1/4-inch threaded insert** for camera-rig mounting — example: https://fr.aliexpress.com/item/1005006071559268.html
- access to the same network as the TriCaster Elite 2

Overall system:

- 1 × **TriCaster Elite 2**
- LAN with 2.4 GHz Wi-Fi
- optional Windows computer, or the TriCaster itself, for the Manager

## 3D-printed enclosure and camera mounting

The repository includes the enclosure model:

```text
hardware/TALLY_TRICASTER_v6.3mf
```

The enclosure is designed to be printed in **PLA**.

It includes a seat for a **1/4-inch threaded insert**, allowing the tally to be mounted to common camera-rig accessories such as:

- magic arms / articulated arms
- mini ball heads
- cold-shoe / flash-shoe adapters
- other camera accessories using a 1/4-inch mounting thread

Example threaded insert:

https://fr.aliexpress.com/item/1005006071559268.html

The enclosure is designed around **2 RGB LEDs only**.

### Camera power

On a **Sony FX6**, the tally can be powered directly from the camera's USB-C port using a **USB-C to USB-C cable**.

If camera USB-C power is not available, any standard **5 V USB-C power supply** is sufficient.

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
3. Select:
   ```text
   NodeMCU 1.0 (ESP-12E Module)
   ```
4. Open:
   ```text
   TriCaster_Elite2_Tally_ESP8266.ino
   ```
5. Enter your Wi-Fi details:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
```

6. Select the tally number:

```cpp
#define DEFAULT_TALLY_NUMBER 1
```

7. Compile and upload.

Serial monitor:

```text
115200 baud
```

## Choosing the TriCaster Elite 2 IP

Public example:

```text
TriCaster Elite 2 : 192.168.1.50
Gateway           : 192.168.1.1
Subnet            : 255.255.255.0
```

Firmware:

```cpp
config.tricaster[0] = 192;
config.tricaster[1] = 168;
config.tricaster[2] = 1;
config.tricaster[3] = 50;
```

Replace these values with the actual TriCaster address and update the gateway, DNS and broadcast address to match your network.

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

Firmware logic:

```cpp
config.ip[0] = 192;
config.ip[1] = 168;
config.ip[2] = 1;
config.ip[3] = 80 + constrain(DEFAULT_TALLY_NUMBER, 1, 8);
```

Keep these static addresses outside your DHCP pool or reserve them in your router.

## Camera/input assignment

By default:

```cpp
config.camera = constrain(DEFAULT_TALLY_NUMBER, 1, 8);
```

Therefore:

```text
TALLY-01 → input1
TALLY-02 → input2
TALLY-03 → input3
...
```

Assignments can later be changed from the Manager without reflashing the tally.

## Manager

File:

```text
TriCaster_Elite2_Tally_Manager.py
```

Features:

- automatic tally discovery
- online/offline status
- IP and RSSI
- camera/input assignment
- PROGRAM and PREVIEW colors
- per-device brightness
- Identify
- remote reboot
- device name and IP configuration
- mobile interface

Ports:

| Function | Port |
|---|---|
| Manager web UI | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| ESP8266 HTTP API | TCP `80` |

Local UI:

```text
http://127.0.0.1:8099
```

Mobile/LAN UI:

```text
http://MANAGER_PC_IP:8099/mobile
```

The public Manager uses `192.168.1.50` as its example TriCaster IP. Replace all occurrences of this address with your own TriCaster IP before building the EXE.

## Building the Windows Manager

```powershell
py -m pip install pyinstaller
```

Console build:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --console --name TriCaster_Elite2_Tally_Manager TriCaster_Elite2_Tally_Manager.py
```

Background build:

```powershell
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
