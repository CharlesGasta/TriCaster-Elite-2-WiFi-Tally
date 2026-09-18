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

## Réseau Wi-Fi, roaming et installations multi-points d'accès

Le firmware prend en charge **un nombre quelconque de points d'accès Wi-Fi** diffusant le même réseau. Il n'est pas limité à 2 AP : une installation avec **3, 4, 5, 6 AP ou davantage** fonctionne avec la même logique.

### Architecture recommandée

```text
                         ┌── AP 1 ))))
TriCaster ── Switch/LAN ─┼── AP 2 ))))
                         ├── AP 3 ))))
                         ├── AP 4 ))))
                         └── AP N ))))
```

Tous les points d'accès doivent appartenir au **même LAN / même sous-réseau IP** que le TriCaster et les tally.

Pour chaque AP :

- mode **Access Point / Bridge**
- liaison montante **Ethernet filaire** recommandée
- **même SSID**
- **même mot de passe**
- **même mode de sécurité** ; WPA2-PSK est recommandé pour la compatibilité ESP8266
- pas de NAT sur les AP secondaires
- pas de serveur DHCP supplémentaire ; un seul équipement du réseau doit assurer le DHCP
- les AP peuvent être de marques différentes si ces règles sont respectées
- le 802.11r/k/v n'est pas nécessaire : le firmware ESP8266 gère lui-même la sélection du meilleur BSSID

Évitez le mode répéteur Wi-Fi ou un backhaul radio lorsque vous pouvez tirer un câble Ethernet. Pour une production critique, le **backhaul filaire** est nettement préférable.

### Plan de canaux 2,4 GHz

Utilisez une largeur de canal de **20 MHz** et privilégiez les canaux non chevauchants **1, 6 et 11**.

Exemple pour six AP :

| AP | Canal |
|---|---:|
| AP 1 | 1 |
| AP 2 | 6 |
| AP 3 | 11 |
| AP 4 | 1 |
| AP 5 | 6 |
| AP 6 | 11 |

À partir du 4e AP, réutilisez les canaux en espaçant physiquement autant que possible deux AP utilisant le même canal. Le but est d'éviter que deux cellules voisines émettent sur la même fréquence.

Dans un lieu très grand, une puissance maximale sur tous les AP n'est pas toujours idéale. Commencez avec une puissance adaptée à la zone à couvrir ; si les cellules se chevauchent fortement, réduisez la puissance afin de garder des zones radio distinctes.

### Roaming automatique des tally

Chaque point d'accès possède un **BSSID** différent, même lorsqu'ils diffusent tous le même SSID. L'ESP8266 garde son IP et choisit automatiquement le BSSID le plus approprié.

Paramètres par défaut :

```cpp
const int ROAM_RSSI_TRIGGER = -70;       // recherche seulement si l'AP courant devient faible
const int ROAM_MIN_GAIN = 8;             // nouvel AP au moins 8 dB meilleur
const unsigned long ROAM_COOLDOWN = 15000;
```

Ainsi, un tally ne change pas d'AP simplement parce qu'un autre est 1 ou 2 dB meilleur. Il reste sur son AP tant que la liaison est correcte, ce qui évite l'effet « yoyo » dans les zones de recouvrement.

Exemple :

```text
AP actuel : -73 dBm
AP voisin : -61 dBm
→ bascule automatique

AP actuel : -71 dBm
AP voisin : -67 dBm
→ aucune bascule
```

Pendant un roaming volontaire, le changement d'AP est **invisible pour le cadreur** : l'ESP conserve le dernier état PROGRAM / PREVIEW / OFF jusqu'à la reprise des données TriCaster.

### Signification des indications réseau

- 🔵 **bleu fixe** : réseau Wi-Fi recherché / hors couverture
- 🔵 **bleu clignotant** : réseau trouvé, association Wi-Fi en cours
- 🟡 **jaune** : Wi-Fi connecté mais communication avec le TriCaster perdue
- lors d'un roaming volontaire vers un meilleur AP : **aucune indication de panne**, le dernier tally reste affiché

Le statut HTTP/heartbeat expose également :

```text
rssi
bssid
channel
wifi_state
```

Ces informations permettent au Manager d'indiquer le point d'accès utilisé par chaque tally et de contrôler la couverture d'une installation multi-AP.

## Boîtier 3D et fixation caméra

Le modèle 3D du boîtier et les informations d'impression sont disponibles sur Thingiverse :

**[Télécharger le modèle 3D sur Thingiverse](https://www.thingiverse.com/thing:7408102)**

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
- **BSSID / point d'accès actuellement utilisé**
- **canal Wi-Fi**
- **état Wi-Fi : connected / roaming / searching / connecting**
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

## Wi-Fi network, roaming and multi-AP deployments

The firmware supports **any number of Wi-Fi access points** broadcasting the same network. It is not limited to two APs: deployments with **3, 4, 5, 6 or more APs** use the same roaming logic.

Recommended topology:

```text
                         ┌── AP 1 ))))
TriCaster ── Switch/LAN ─┼── AP 2 ))))
                         ├── AP 3 ))))
                         ├── AP 4 ))))
                         └── AP N ))))
```

All APs must be on the **same Layer-2 LAN / IP subnet** as the TriCaster and tally units.

Configure every AP with:

- **Access Point / Bridge** mode
- preferably a **wired Ethernet backhaul**
- the **same SSID**
- the **same password**
- the **same security mode**; WPA2-PSK is recommended for ESP8266 compatibility
- no NAT on secondary APs
- no additional DHCP server; use one DHCP server for the LAN
- different AP brands are acceptable when these requirements are met
- 802.11r/k/v is not required; the ESP8266 firmware performs its own BSSID selection

For production use, wired backhaul is strongly preferred over wireless repeater/mesh backhaul.

### 2.4 GHz channel plan

Use **20 MHz** channel width and the non-overlapping channels **1, 6 and 11**.

For six APs, a typical plan is:

| AP | Channel |
|---|---:|
| AP 1 | 1 |
| AP 2 | 6 |
| AP 3 | 11 |
| AP 4 | 1 |
| AP 5 | 6 |
| AP 6 | 11 |

From the fourth AP onward, reuse channels only with as much physical separation as practical between APs sharing the same channel.

### Automatic roaming

Every AP has a different **BSSID**, even when all APs use the same SSID. The tally keeps its IP address and automatically selects a better BSSID when necessary.

Default roaming parameters:

```cpp
const int ROAM_RSSI_TRIGGER = -70;
const int ROAM_MIN_GAIN = 8;
const unsigned long ROAM_COOLDOWN = 15000;
```

The tally therefore stays on its current AP while the link remains usable and only moves when another AP is clearly better, preventing ping-pong roaming in overlap areas.

During intentional roaming, the switch is **invisible to the camera operator**: the last PROGRAM / PREVIEW / OFF state remains displayed until TriCaster polling resumes.

Network indications:

- 🔵 **solid blue**: searching for the Wi-Fi network / out of coverage
- 🔵 **blinking blue**: network found, Wi-Fi association in progress
- 🟡 **yellow**: Wi-Fi is connected but TriCaster communication is lost
- intentional roaming: no fault indication; the previous tally state is held

The status/heartbeat payload also includes `rssi`, `bssid`, `channel` and `wifi_state` for multi-AP diagnostics.

## 3D-printed enclosure and camera mounting

The enclosure 3D model and print information are available on Thingiverse:

**[Download the 3D model on Thingiverse](https://www.thingiverse.com/thing:7408102)**

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
- **current AP / BSSID**
- **Wi-Fi channel**
- **Wi-Fi state: connected / roaming / searching / connecting**
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
