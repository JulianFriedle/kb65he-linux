# Research: live key depth (issue #3)

Question: does the KB65HE 8k firmware expose how deep a key is pressed (0 to 4.0 mm) over the
vendor HID interface, so that the GUI could show it live?

**Conclusion: unlikely, but not excluded.** Nothing in the vendor software reads or even
mentions analog key travel. There is no command, no pushed report and no UI for it. The only
way to be sure is to ask the real keyboard, which is what `kb65he probe` is for (instructions
at the end, in German).

Everything below is static analysis of the Windows software (decompiled `DevicePlus.dll`,
`DaemonApi.dll`, the C# UI). No hardware was available for this research. File references are
to the local decompilation output (`out/DevicePlus.c`, `out/DaemonApi.c`) and the decompiled
C# project `device_KG657U_UK`; function names are Ghidra addresses.

## 1. Every HID command the plugin can send

All traffic to the keyboard goes through one function, `FUN_180043f10` (`DevicePlus.c:60086`,
its own log string names it `CPxUsbBt24GDev<CPxDev<CPxHidInterrupt>, _CMD_DATA_PACKET_USB_BT<64>>::SendCmd`).
It is only reached from three places:

| Path | Function | Command ids found at the call sites |
|---|---|---|
| generic GET helper | `FUN_18001dd60` (`:25539`), `FUN_18001d830` (`:25176`) | `0x01`, `0x05`, `0x0D`, `0x19`, `0x1B` (e.g. `:36247`, `:40891`, `:40967`, `:40980`, `:40983`), `0x21` (`:41366`), `0x35` (`:47829`) |
| generic SET helper | `FUN_180045450` (`:60898`) | `0x00`, `0x18`, `0x1A`, `0x20`, `0x30`, `0x34` (e.g. `:19745`, `:19812`, `:19907`, `:20015`, `:20083`, `:20093`) |
| inline request packets in the load/sync functions (`FUN_1800296c0` ... `FUN_18003d960`, `FUN_180046100`, `FUN_1800465d0`, `FUN_180046aa0`, `FUN_180046f70`) | packet is built as `_local_xxx = 0xNN00`, i.e. byte 1 = command | `0x01`, `0x05`, `0x21`, `0x31`, `0x35` (`:33821`, `:34131`, `:34472`, `:41091`, `:41527`, `:41909`, `:61791` ...) |

I went through every function that contains one of these call sites and the helpers
themselves; there is no other literal command id. The complete set is therefore:

| Write (even) | Read (odd) | Meaning | Status |
|---|---|---|---|
| `0x00` | `0x01` | active trigger layer (low-latency mode) | known; the 8k returns no data for the read |
| | `0x05` | change counter / revision | known |
| | `0x0D` | serial | known |
| `0x18` | `0x19` | lighting | known |
| `0x1A` | `0x1B` | key map | known |
| `0x20` | `0x21` | DKS | partly known (write layout not decoded) |
| `0x30` | `0x31` | trigger table | known |
| `0x34` | `0x35` | SOCD | partly known (read needs a request payload) |

There is **no command id outside these 14**. No "test", "calibration", "ADC", "magnet" or
"travel" string exists in `DevicePlus.dll`, `DaemonApi.dll` or `DeviceDaemon.exe`
(`strings` in ASCII and UTF-16 for calib, magnet, adc, travel, depth, analog, hall, realtime,
key state: the only hit is the Thrift message "Exceeded depth limit"). The strings that do
exist are Thrift runtime messages, the source file names `PxUsbBT24GDev.h` /
`PxBinaryFile.cpp`, `debug.ini` and `ID_PROFILE_*`.

## 2. Things that looked promising and are not

* **`kmpDaemonSDK_TestGet` / `TestSet`** (`DeviceUI.SDK/kmp_SDK.cs:255-259`, the issue's main
  hint). They are imported from `kmpDaemonSDK.dll`, not from `DaemonApi.dll`. That DLL is not
  part of the package (`strings` finds no reference to it in `DaemonApi.dll`,
  `DevicePlus.dll` or `DeviceDaemon.exe`), and the C# project never calls them (`grep` for
  `TestGet|TestSet|kmpDaemonSDK` finds only the declarations). `kmp_SDK.cs` is an unused
  copy from another product line (parameters are called `_lpszDonglePath`,
  `SetButtonFunction2`, "Dongle"); the project only uses its struct helpers
  (`StructToBytes`, `ByteToStruct`). Conclusion: dead code, not a hidden test mode.
* **`DaemonApi.dll` exports** (33 `DeviceApi_*` functions) map to daemon function codes
  `0, 1, 2, 9, 0x18, 0x19, 0x1C, 0x1D, 0x20, 0x21, 0x24-0x27, 0x30, 0x31, 0x34, 0x35, 0x40-0x44, 0x46-0x49`
  (`DaemonApi.c:12411-14138`). The plugin's dispatcher `FUN_1800238a0` (`DevicePlus.c:29810`,
  `out/FUN_1800238a0.c`) implements the same codes and **does not talk to the hardware**: each
  case reads or writes the in-memory profile model of the device
  (`FUN_18001e950`, `FUN_18001d4f0`, ...). Hardware access happens only when the model is
  synchronised (`FUN_1800187c0`, `FUN_180039130`), and that uses the commands from section 1.
  There is no daemon code that the C# never calls, and none that reads live data.
  `DeviceApi_RestoreFactory` (code 9) just copies a default profile into the model and
  syncs it with the normal writes; `GetFirmwareVersion` (code 2) is answered from cached data
  (not traced further).
* **Magnetism structs.** `KEY_MAGNETISM_INFO`, `KEY_MAGNETISM_DKS_INFO`,
  `KEY_MAGNETISM_RT4_INFO` (`Device_SDK.cs:24-110`, `DeviceApi_KeyCollaboration_Case.cs:43-68`)
  describe the stored DKS and rapid-trigger settings (start/end distances), not measurements.
* **The UI.** No page, control or timer in `Device.cs` / `DeviceSOCD.cs` shows a live travel
  value; the only live element is the lighting preview. A search for `calib|analog|depth|travel|realtime`
  in the C# sources finds only unrelated hits (`System.Drawing`).

## 3. Pushed input reports (new finding)

The keyboard sends unsolicited reports, and the vendor software reacts to them. The receive
handler is `FUN_1800403f0` (`DevicePlus.c:57446`, copies for the other layouts follow it):

* The incoming buffer is split into chunks of 64 bytes plus one leading report-id byte.
  `byte 0 == 0` is a response to a request; it goes to `FUN_180043440` (`:59525`), which matches
  it with the pending request by command id (`byte1 & 0x3F`) and signals the waiting thread.
* `byte 0 == 4` (and length >= 4) is an **event**. `byte 1` is the event code:

| Code | Reaction in the plugin (`:57511-57560`) and the C# UI (`Device.cs:1184-1226`, `DeviceSOCD.cs:1495-1540`) |
|---|---|
| `0x94` | lighting effect changed, `byte 3` = effect (clamped to 0..10) |
| `0x95` | colour slot changed, `byte 3` (clamped to 0..6) |
| `0x96` | brightness changed, `byte 3` (clamped to 0..9) |
| `0x97` | speed changed, `byte 3` (clamped to 0..3) |
| `0x9C` | SOCD changed, `byte 7` is stored (`:57235`, SOCD layouts only); UI re-reads SOCD |
| `0x9E` | profile / layer switched on the keyboard; the plugin reloads the profile, the UI reloads everything |
| `0x9F` | rapid-trigger distances changed on the keyboard (Fn adjustment mode); the UI re-reads them |
| `0x98`-`0x9B`, `0x9D` | forwarded to the UI, which deliberately ignores them (`case 152..155, 157: break`) |

All events are forwarded to the UI callback (`LPFN_FW_UPDATE_PROGRESS`, `Device_SDK.cs:13`)
with the raw buffer. They are **configuration-change notifications** (the user pressed an
Fn shortcut on the keyboard), not key states. Nothing in them carries a position.

Open points:

* The five ignored codes `0x98`-`0x9B` and `0x9D` are unexplained. The numbering
  (`0x94`-`0x9F`) overlaps the low six bits of the command ids `0x14`-`0x1F`, so these may be
  "something of kind X changed" notifications. They are not key depth.
* It is not known on which hidraw node the report-id-4 events arrive on Linux. The config
  interface in this project is used without report ids (`docs/PROTOCOL.md`), so the events
  probably come from another HID interface of the keyboard, or the vendor interface declares
  report id 4 additionally. `kb65he probe` therefore prints the report descriptors of
  all hidraw nodes and `--watch` listens on all of them.

Normal key presses are visible as regular HID keyboard reports (the GUI already uses the
scancodes for the "pressed" highlight). Those carry on/off only.

## 4. Assessment

For: a hall-effect keyboard measures travel in firmware, and an analog read-out would be
technically trivial. Some other hall-effect boards expose it as a polled command.

Against, in order of weight:

1. The vendor plugin has a closed command set of 14 ids and none of them can plausibly carry
   a per-key travel (all are configuration blocks).
2. The vendor configurator has no travel visualisation, which is a standard selling point on
   comparable products. If the firmware could deliver it cheaply, the UI would very likely
   use it.
3. The event mechanism only announces configuration changes.
4. The 8k polling rate is spent on the normal HID reports; the config interface answers one
   request per packet.

Rough estimate: 10-20 % that a hidden read command with depth data exists. Even then it
probably needs a parameter (for example a key index), and a probe with empty payload would see
that only as a status other than `NOT_SUPPORTED`. That is why the probe reports "recognised"
ids separately from ids that return data.

## 5. The probe: `kb65he probe`

Code: `src/kb65he/probe.py`, CLI in `src/kb65he/cli.py`, tests in `tests/test_probe.py`.

Safety guarantees (each one is enforced in code and covered by a test):

* **Only read commands.** Requests are built by `build_read_request`, which accepts only odd ids
  `0x01..0x3F`. Even ids (all writes: `0x00`, `0x18`, `0x1A`, `0x20`, `0x30`, `0x34`, and every
  unknown even id) raise `UnsafeCommand`, from the CLI options (`--ids`, `--repeat`), from the
  API and from the packet layer.
* **Packet-level check.** `check_read_only_packet` accepts nothing but a single 64-byte type-0
  packet with an odd command id, zero length, all-zero payload and a valid checksum. It runs in
  `ReadOnlyLink.request` and again inside `HidrawProbeDevice.exchange`, immediately before
  `os.write`. A hand-made write packet is refused even if someone bypasses the link class.
* **No payload, no multi-packet transfers.** Nothing can be written "through" a read id.
* **One request per id, short timeout (0.5 s), no retries.** Busy answers are recorded, not
  retried. `--repeat` is limited to 50 requests per second.
* **Control read.** `0x05` (a harmless known read) is sent before and after the scan. If the
  first one does not answer, nothing else is sent. If the second one fails, the tool warns.
* **`--watch` cannot write.** It opens the hidraw nodes with `O_RDONLY`.
* **The scan asks first** (Enter to continue) unless `--yes` is given.
* **No serial number** is requested (`0x0D` is not used), so the report contains none. It does
  contain the report descriptors, the kernel version and the raw answers.

The residual risk is the firmware itself: "odd = read" holds for all 8 known pairs and is the
protocol convention, but it cannot be proven for ids nobody has seen. Settings live in the
keyboard's flash and the probe never sends a write, so the realistic worst case is a firmware
that stops answering until it is replugged.

Modes:

| Command | What it does |
|---|---|
| `kb65he probe` | scan: one empty read request for each of the 24 unknown odd ids, classified as `data`, `empty`, `status:<NAME>`, `bad-checksum` or `timeout` |
| `kb65he probe --watch 30` | passive: print every report from all hidraw nodes of the keyboard for 30 s, labelled when it is a known event |
| `kb65he probe --repeat 0x0B` | poll one read command (10 times per second, 15 s), print a line whenever a byte of the answer changes, changed bytes marked |
| `--out FILE` | JSON report path, default `kb65he-probe-<mode>-<time>.json` in the current directory |
| `--ids 0x03,0x07` | restrict the scan to some ids |
| `--demo` | global option, goes **before** `probe` (`kb65he --demo probe …`): simulated keyboard, no hardware |

## 6. Anleitung für den Maintainer (Deutsch)

Ziel: herausfinden, ob die Tastatur irgendwo Tiefenwerte liefert. Dauer insgesamt etwa 10 Minuten.
Es werden nur Lese-Befehle (ungerade IDs) gesendet. Die Tastatureinstellungen werden dabei
nicht verändert.

### Vorbereitung

1. Tastatur direkt am Rechner anstecken (kein Hub, kein KVM) und das normale Profil lassen,
   wie es ist.
2. Die GUI schließen (`kb65he-gui`), damit nichts anderes mit der Tastatur spricht.
3. Die udev-Regel muss installiert sein (README, Abschnitt Installation). Test:
   `kb65he info` zeigt Serial und Revision an. Falls nicht installiert, Regel installieren und
   Tastatur ab- und wieder anstecken.
4. Ein Terminal öffnen und in den Ordner mit dem Repository wechseln, auf den Branch
   `research/key-depth` (oder nach dem Merge auf `main`):

   ```bash
   cd ~/kb65he-linux            # Pfad anpassen
   git fetch origin
   git checkout research/key-depth
   mkdir -p ~/kb65he-probe && cd ~/kb65he-probe
   ```

   Die Report-Dateien landen im aktuellen Ordner, hier also in `~/kb65he-probe`.
5. Den Befehl festlegen. Ohne Installation, direkt aus dem Repository:

   ```bash
   alias kbprobe='PYTHONPATH=$HOME/kb65he-linux/src python3 -m kb65he.cli probe'
   ```

   (Pfad wie in Schritt 4.) Ist das Paket installiert und aktuell, geht stattdessen
   `alias kbprobe='kb65he probe'`.
6. Funktionstest ohne Tastatur-Risiko: `PYTHONPATH=$HOME/kb65he-linux/src python3 -m kb65he.cli --demo probe -y --out demo.json` (`--demo` steht vor `probe`). Es sollte eine Liste
   mit `timeout`/`data`-Zeilen und "Report written to demo.json" erscheinen.

### Schritt 1: passiv mithören (sendet nichts)

```bash
kbprobe --watch 40 --out probe-watch.json
```

Gleich nach dem Start erscheinen die Zeilen pro hidraw-Gerät (Interfaces, `report ids`). Dann
innerhalb der 40 Sekunden, in dieser Reihenfolge:

1. 5 Sekunden nichts drücken (zeigt, ob die Tastatur von selbst Daten schickt).
2. Einzelne Buchstabentasten langsam bis zum Anschlag drücken und loslassen (W, A, S, D, Leertaste), je einmal.
3. Eine Taste langsam halb herunterdrücken und halten, dann loslassen.
4. Die Beleuchtung per Fn-Kombination an der Tastatur ändern (Effekt, Helligkeit oder Farbe
   wechseln, je nachdem was die Tastatur dafür vorsieht). Das ist die Positivkontrolle: dabei
   sollten Zeilen mit `EVENT 0x94`, `0x95`, `0x96` oder `0x97` erscheinen. Kommt nichts, hört
   das Tool auf dem falschen Gerät mit, und die Datei ist trotzdem wertvoll.
5. Optional: Fn+Tab (Einstellmodus für den Rapid Trigger) kurz benutzen, erwartet wird `EVENT 0x9F`.

Notiere dir, bei welchem Schritt welche Zeilen kamen. Mit Strg+C kann abgebrochen werden, die
Datei wird trotzdem geschrieben.

### Schritt 2: alle unbekannten Lese-Befehle einmal abfragen

```bash
kbprobe --out probe-scan.json
```

Das Tool zeigt die 24 IDs, die es senden wird, und wartet auf Enter. Währenddessen keine Taste
drücken. Es dauert etwa 15 Sekunden. Am Ende steht eine Zusammenfassung:

* `interesting`: IDs, die Daten geliefert haben (am wichtigsten).
* `recognised`: IDs, die mit einem anderen Status als `NOT_SUPPORTED` geantwortet haben (z. B.
  `BAD_DATA`). Die ID existiert dann wahrscheinlich und will einen Parameter, zum Beispiel
  eine Tastennummer.
* `timeouts` und `error_status`: erwartetes Rauschen.
* `control_ok_after`: muss `True` sein. Bei `False` die Tastatur ab- und wieder anstecken.

### Schritt 3: nur falls Schritt 2 `interesting` IDs gefunden hat

Für jede ID unter `interesting` (hier als Beispiel `0x0B`, die ID durch die gefundene ersetzen):

```bash
kbprobe --repeat 0x0B --seconds 25 --out probe-repeat-0x0B.json
```

Während der 25 Sekunden: nacheinander verschiedene Tasten (W, A, Leertaste, eine Taste weit
rechts) jeweils langsam bis zum Anschlag drücken, 2 Sekunden unten halten, langsam
loslassen. Immer nur eine Taste auf einmal. Das Tool druckt eine Zeile, sobald sich ein Byte
der Antwort ändert; geänderte Bytes stehen in `[eckigen Klammern]` (im Terminal rot). Am Ende
steht `answer changed while polling` oder `answer never changed`.

Kontrolltest für die Methode (optional, 5 Sekunden): `kbprobe --repeat 0x05 --seconds 5
--out probe-repeat-0x05.json`. Das ist ein bekannter Befehl, dessen Antwort sich nicht ändern
darf (`answer never changed`).

### Schritt 4: Ergebnisse an Issue #3 anhängen

Alle `probe-*.json`-Dateien aus `~/kb65he-probe` an das Issue #3 anhängen
(`ls ~/kb65he-probe`). Mindestens:

* `probe-watch.json`
* `probe-scan.json`
* `probe-repeat-<ID>.json`, falls Schritt 3 gemacht wurde

Zusätzlich ein, zwei Sätze, was bei welchem Schritt auf dem Bildschirm passierte (vor allem
Schritt 1.4). In den Dateien stehen keine Seriennummer und keine Tastatureinstellungen,
aber Kernel-Version, hidraw-Pfade, Report-Deskriptoren und die rohen Antworten.

### Wie die Ergebnisse zu lesen sind

| Ergebnis | Bedeutung | Nächster Schritt |
|---|---|---|
| Scan: nichts bei `interesting` und `recognised` | Es gibt keinen leicht auffindbaren Lese-Befehl für Tiefe. Issue als "nicht möglich mit bekannter Firmware" schließen. | keiner |
| Scan: `recognised` mit `BAD_DATA` o. Ä., aber keine Daten | Befehl existiert und braucht Parameter. | Probe um eine Anfrage mit Nutzdaten (Tastennummer) erweitern, bewusst und getrennt vom sicheren Modus |
| `interesting` und `--repeat` zeigt Änderungen beim Drücken | Tiefenwerte gefunden. | Bytes-Offsets und Wertebereich aus `value_ranges` im Report nehmen, daraus `read_key_depth()` und die GUI-Anzeige bauen (nicht Teil dieses Branches) |
| `interesting`, aber `answer never changed` | Statischer Befehl (Konfiguration oder Info). | In `docs/PROTOCOL.md` dokumentieren |
| Watch: `EVENT 0x94-0x9F` beim Beleuchten, nichts beim Tastendruck | Wie erwartet: Events melden nur Konfigurationsänderungen. | keiner |
| Watch: Zeilen mit `report id 4, unknown code` oder unbekannte Reports beim Tastendruck | Neue Information. | Datei anhängen, dann gezielt auswerten |

## 7. Library and GUI

Because the research found no concrete depth command, `read_key_depth()` and a GUI overlay
were deliberately **not** added. As soon as the probe finds a command, the plan is:
`KB65HE.read_key_depth() -> dict[int, float]` next to `read_trigger()` in `device.py`, plus
an optional fill bar in `KeyboardView` (`gui/widgets.py`) that is only enabled when the
device answers the command.
