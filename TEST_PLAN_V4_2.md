# V4.2 field validation plan

Use this checklist before publishing V4.2 as the production baseline.

## Fleet

Validate all 6 tally units together on the same production LAN.

## 1. Startup

For every tally:

- boots normally
- joins the configured 2.4 GHz Wi-Fi
- receives the expected DHCP/static address
- appears in the Manager
- correct tally name and camera assignment
- firmware reports V4.2.0
- RSSI, BSSID, channel and DHCP IP are visible
- no repeated Wi-Fi disconnect reason in Serial Monitor

## 2. TriCaster tally states

For every assigned input:

- PROGRAM -> red
- PREVIEW -> green
- neither -> LEDs off
- TriCaster unavailable -> yellow/error
- recovery restores the correct tally state without reboot

## 3. Stability soak

Run all 6 tally units continuously for at least 60 minutes.

Pass criteria:

- no unexplained Manager offline event
- no ESP reboot
- no progressive latency increase
- heartbeat remains regular
- Wi-Fi loss counters stay stable in fixed coverage

## 4. Multi-AP roaming

Test only where multiple APs use the same SSID/security and the same Layer-2 LAN.

- move a tally from good coverage on AP A toward AP B
- roaming should only start below about -72 dBm
- target AP should be at least 10 dB better
- PROGRAM/PREVIEW display should remain visually stable during the handoff
- Manager should show the new BSSID/channel afterward
- no repeated ping-pong between APs

## 5. Manager controls

Check:

- camera assignment
- brightness
- PROGRAM/PREVIEW colors
- Identify
- reboot
- DHCP/static configuration
- displayed current DHCP IP
- Production Mode lock
- pre-flight report

## 6. OTA

Test on one tally first:

1. select one tally
2. upload the matching V4.2 .bin
3. verify reboot and return to Manager
4. verify firmware version, Wi-Fi and tally data
5. only then test a selected group
6. deploy to the remaining units only after successful validation

## Acceptance

V4.2 can be treated as production-ready after all 6 units complete the soak, roaming and OTA tests without unexplained disconnects or reboots.
