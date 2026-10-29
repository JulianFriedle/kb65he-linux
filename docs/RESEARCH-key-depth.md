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

## 5. The probe tool (not part of main)

A read-only probe (`kb65he probe` with `--watch`, a scan of unknown odd ids and `--repeat`) was
written for this investigation and run once on real hardware (results below). It is **not** shipped
in the main code: its question is answered, and its scan made the keyboard drop off the bus. The
code is preserved on the branch
[`research/key-depth-probe`](https://github.com/JulianFriedle/kb65he-linux/tree/research/key-depth-probe)
(it stops after 3 unanswered requests in a row). Only rerun it if a firmware update adds features,
and prefer the passive `--watch` mode, which sends nothing.

## 6. Hardware results (2026-10-29, KB65HE 8k ISO, 3367:5035)

* `--watch 40`: key presses only appear on the normal keyboard interfaces (`hidraw2` report id 1,
  `hidraw4` report id 2) as plain on/off reports. **Nothing** arrived on the vendor interface
  (`hidraw3`) or as report-id-4 events while pressing keys. No depth data is pushed.
* Scan: the control read `0x05` answered; **every unknown odd id timed out** (no answer at all, not
  even `NOT_SUPPORTED`). After ~23 unanswered requests the keyboard dropped off the bus
  (`EIO` on hidraw) and had to be replugged. Afterwards it enumerated normally (`3367:5035`), the
  change counter was unchanged (nothing was written), but the trigger table read back different
  values than before (actuation and rapid trigger back to 1.0 / 1.0 mm), i.e. the crash reset the
  trigger table to defaults without increasing the change counter.
* Consequence for the probe: the scan now stops after 3 unanswered requests in a row and handles a
  disappearing device. **Do not run the full scan again.**
* A normal unplug/replug keeps all settings; the reset above was caused by the crash only. A saved
  profile (`kb65he profile load`) restored the previous state immediately.
* Conclusion: no live key-depth data is available from this firmware through the configuration
  interface. Issue #3 can be closed as "not possible with the current firmware".
