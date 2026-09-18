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
- **Client Isolation / AP Isolation désactivé**
- pas de réseau Guest isolé : les ESP doivent pouvoir joindre le TriCaster et le Manager
- ne pas bloquer l'UDP broadcast local ; le Manager découvre les tally via UDP `4210`
- éviter les fonctions agressives de broadcast/multicast suppression sur le VLAN tally
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

Pour une production critique, alimentez idéalement **routeur + switch PoE + AP principaux sur onduleur (UPS)**. Une panne du cœur réseau ferait sinon tomber tous les tally simultanément.

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
5. Choisir uniquement le numéro du boîtier avant le premier flash :

```cpp
#define DEFAULT_TALLY_NUMBER 1
```

6. Compiler puis téléverser.

Le firmware V4 conserve toujours des valeurs par défaut compilables :

```cpp
const char* DEFAULT_WIFI_SSID = "YOUR_WIFI_SSID";
const char* DEFAULT_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEFAULT_ADMIN_TOKEN = "CHANGE_ME";
```

Mais **il n'est plus nécessaire de reflasher le tally pour changer le réseau**.

Moniteur série :

```text
115200 baud
```

---

## Configuration réseau sans reflasher

### Premier démarrage / réseau introuvable

Au démarrage, le tally cherche le réseau enregistré. S'il ne le trouve pas pendant environ **30 secondes**, il crée automatiquement son propre point d'accès :

```text
TALLY-01-SETUP
TALLY-02-SETUP
...
```

Le mot de passe de ce Wi-Fi SETUP est le **token administrateur**. Sur un firmware neuf, la valeur initiale est :

```text
CHANGE_ME
```

Connectez un téléphone ou un ordinateur au réseau `TALLY-XX-SETUP`, puis ouvrez :

```text
http://192.168.4.1/
```

Le portail permet de régler :

- nom du tally
- SSID Wi-Fi 2,4 GHz
- mot de passe Wi-Fi
- mode **DHCP** ou **IP statique**
- IP, gateway, subnet et DNS en mode statique
- IP du TriCaster
- token administrateur

Après validation, l'ESP enregistre la configuration en EEPROM puis redémarre.

> Pour la sécurité, remplacez immédiatement `CHANGE_ME` par un token personnel de **8 à 32 caractères**. Ce token protège l'API d'administration, la mise à jour OTA et le réseau de secours `TALLY-XX-SETUP`.

### DHCP ou IP statique

Les deux modes sont supportés.

**IP statique** est pratique pour un parc broadcast fixe :

```text
TALLY-01 : 192.168.1.81
TALLY-02 : 192.168.1.82
...
```

Gardez ces adresses **hors de la plage DHCP** du routeur.

**DHCP** est pratique lorsque le système est déplacé sur des réseaux différents. Pour conserver des adresses prévisibles, utilisez de préférence des **réservations DHCP** sur le routeur.

Le Manager V4 permet ensuite de modifier ces paramètres à distance sans reflasher l'ESP.

### Migration depuis l'ancien firmware

Le firmware V4 reconnaît automatiquement la configuration EEPROM de la version précédente et conserve notamment :

- nom du tally
- IP statique
- IP TriCaster
- caméra assignée
- couleurs PROGRAM / PREVIEW
- luminosité

Les nouveaux paramètres réseau sont ajoutés avec leurs valeurs par défaut.

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

## Tally Manager V4

Fichier :

```text
TriCaster_Elite2_Tally_Manager.py
```

Le Manager n'est toujours **pas dans le chemin critique du tally** : si le Manager est fermé, chaque ESP continue à lire directement le TriCaster.

Le Manager V4 fournit :

- détection automatique des tally
- état connecté / hors ligne
- RSSI avec indication visuelle de qualité
- **BSSID / point d'accès utilisé**
- nom convivial des AP, par exemple `AP TERRAIN`, `AP TRIBUNE`
- canal Wi-Fi
- état Wi-Fi : `connected`, `roaming`, `searching`, `connecting`
- version firmware
- uptime ESP
- latence de réponse TriCaster
- compteur de roamings
- compteur de pertes Wi-Fi
- compteur de pertes TriCaster
- affectation caméra 1 à 32
- couleurs PROGRAM / PREVIEW
- luminosité
- Identify
- reboot distant
- configuration complète du réseau ESP
- DHCP / IP statique
- modification de l'IP TriCaster
- **mise à jour OTA de tous les tally connectés**
- interface desktop et mobile

Ports utilisés :

| Fonction | Port |
|---|---|
| Interface web Manager | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| API / OTA ESP8266 | TCP `80` |

Interface locale :

```text
http://127.0.0.1:8099
```

Depuis un téléphone sur le même réseau :

```text
http://IP_DU_PC_MANAGER:8099/mobile
```

### Authentification

Le Manager et les opérations d'administration des ESP utilisent une authentification HTTP Basic :

```text
Utilisateur : admin
Mot de passe : token administrateur
```

La configuration persistante du Manager est enregistrée à côté du script / EXE dans :

```text
tally_manager_config.json
```

Valeur initiale publique :

```json
{
  "api_token": "CHANGE_ME",
  "ap_aliases": {}
}
```

Remplacez `CHANGE_ME` par le **même token que celui configuré dans les ESP** avant une utilisation sur un réseau partagé.

> Le protocole d'administration reste HTTP sur le LAN. Le réseau tally doit donc rester privé / isolé et ne doit pas être exposé directement à Internet.

### Mise à jour OTA

1. Dans Arduino IDE, compilez le firmware et exportez le binaire `.bin`.
2. Ouvrez le Manager V4.
3. Sélectionnez le fichier `.bin` dans **Firmware OTA**.
4. Cliquez **METTRE À JOUR TOUS LES TALLY**.

Le Manager envoie le firmware séquentiellement à tous les tally actuellement en ligne. Chaque ESP redémarre automatiquement après une mise à jour réussie.

Conservez toujours un premier boîtier de test avant de lancer une mise à jour de parc pendant une période de production.

### Diagnostic de couverture

Chaque heartbeat expose notamment :

```text
firmware
rssi
bssid
channel
wifi_state
uptime_ms
tricaster_latency_ms
last_tally_age_ms
roam_count
wifi_loss_count
tricaster_loss_count
last_roam_age_ms
```

Repères pratiques pour le RSSI :

```text
>= -65 dBm     très bon
-66 à -72 dBm  acceptable / à surveiller
< -72 dBm      zone à améliorer
```

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
- **Client Isolation / AP Isolation disabled**
- do not use an isolated guest network; ESP units must reach the TriCaster and Manager
- allow local UDP broadcast; the Manager discovers tally units on UDP `4210`
- avoid aggressive broadcast/multicast suppression on the tally VLAN
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

For critical productions, power the **router + PoE switch + main APs from a UPS** whenever practical. A failure of the network core would otherwise affect every tally at once.

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
5. Select the tally number before the first flash:

```cpp
#define DEFAULT_TALLY_NUMBER 1
```

6. Compile and upload.

V4 still contains compile-time fallback defaults:

```cpp
const char* DEFAULT_WIFI_SSID = "YOUR_WIFI_SSID";
const char* DEFAULT_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEFAULT_ADMIN_TOKEN = "CHANGE_ME";
```

However, **network settings no longer require reflashing the ESP**.

Serial monitor:

```text
115200 baud
```

## Network setup without reflashing

### First boot / configured Wi-Fi unavailable

At startup, the tally searches for the stored Wi-Fi network. If it cannot find it for about **30 seconds**, it automatically creates:

```text
TALLY-01-SETUP
TALLY-02-SETUP
...
```

The SETUP Wi-Fi password is the **administrator token**. On a new public firmware build the initial value is:

```text
CHANGE_ME
```

Connect a phone or computer to `TALLY-XX-SETUP`, then open:

```text
http://192.168.4.1/
```

The setup portal can configure:

- tally name
- 2.4 GHz Wi-Fi SSID
- Wi-Fi password
- **DHCP** or **static IP**
- IP, gateway, subnet and DNS in static mode
- TriCaster IP
- administrator token

The ESP saves the configuration to EEPROM and reboots.

> Replace `CHANGE_ME` immediately with a private **8 to 32 character** token. The token protects the administration API, OTA updates and the fallback `TALLY-XX-SETUP` network.

### DHCP or static IP

Both modes are supported.

Static addresses are convenient for a fixed broadcast system:

```text
TALLY-01 : 192.168.1.81
TALLY-02 : 192.168.1.82
...
```

Keep static tally addresses outside the DHCP pool.

DHCP is convenient for portable deployments. For predictable addresses, use **DHCP reservations** on the router.

The V4 Manager can change these settings remotely without reflashing the ESP.

### Migration from previous firmware

V4 automatically recognizes the previous EEPROM layout and preserves the existing tally name, static IP, TriCaster IP, camera assignment, colors and brightness while adding the new V4 network settings.

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

## Manager V4

File:

```text
TriCaster_Elite2_Tally_Manager.py
```

The Manager is still **not part of the critical tally path**. If the Manager is closed, every ESP continues polling the TriCaster directly.

V4 features include:

- automatic tally discovery
- online/offline status
- RSSI with quality indication
- current **AP / BSSID**
- friendly AP names such as `COURT AP` or `STANDS AP`
- Wi-Fi channel
- Wi-Fi state: `connected`, `roaming`, `searching`, `connecting`
- firmware version
- ESP uptime
- TriCaster response latency
- roaming counter
- Wi-Fi loss counter
- TriCaster loss counter
- camera/input assignment from 1 to 32
- PROGRAM / PREVIEW colors
- brightness
- Identify
- remote reboot
- full ESP network configuration
- DHCP / static IP
- TriCaster IP configuration
- **fleet OTA update for all online tally units**
- desktop and mobile UI

Ports:

| Function | Port |
|---|---|
| Manager web UI | TCP `8099` |
| Discovery / heartbeat | UDP `4210` |
| ESP8266 API / OTA | TCP `80` |

Local UI:

```text
http://127.0.0.1:8099
```

Mobile/LAN UI:

```text
http://MANAGER_PC_IP:8099/mobile
```

### Authentication

The Manager and ESP administration endpoints use HTTP Basic authentication:

```text
Username : admin
Password : administrator token
```

Persistent Manager settings are stored next to the script / EXE:

```text
tally_manager_config.json
```

Default public configuration:

```json
{
  "api_token": "CHANGE_ME",
  "ap_aliases": {}
}
```

Replace `CHANGE_ME` with the **same token configured on the ESP units** before using the system on a shared network.

> Administration uses HTTP on the local LAN. Keep the tally network private / isolated and do not expose these endpoints directly to the Internet.

### OTA firmware update

1. Compile the ESP8266 firmware in Arduino IDE and export the compiled `.bin`.
2. Open Manager V4.
3. Select the `.bin` file under **Firmware OTA**.
4. Click **UPDATE ALL TALLY UNITS** / the corresponding V4 update button.

The Manager sends the firmware sequentially to every currently online tally. Each ESP reboots automatically after a successful update.

Always validate a new firmware on one test tally before deploying it to a live production fleet.

### Coverage diagnostics

Heartbeat/status data includes:

```text
firmware
rssi
bssid
channel
wifi_state
uptime_ms
tricaster_latency_ms
last_tally_age_ms
roam_count
wifi_loss_count
tricaster_loss_count
last_roam_age_ms
```

Useful RSSI reference:

```text
>= -65 dBm     very good
-66 to -72     usable / monitor
< -72 dBm      improve coverage
```

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
