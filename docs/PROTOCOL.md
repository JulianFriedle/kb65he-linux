# KB65HE 8k configuration protocol

Status: partially decoded. Verified on `3367:5035` (ISO), firmware revision as shipped in 2025.

## Transport

* USB interface 2 (`mi_02`), HID usage page `0xFF01`, usage `0x01`.
* 64-byte input and output reports, **no report ID**. On Linux write `0x00` + 64 bytes to the hidraw node.
* Every request packet gets exactly one response packet with the same command id.

## Packet layout

| Byte | Meaning |
|---|---|
| 0 | `0x00` |
| 1 | bits 0–5: command id, bits 6–7: packet type `t` |
| 2 | request: `0`; response: status |
| 3 | payload length + header extra (`t0`: 0, `t1`: 1, `t2`: 2, `t3`: 4) |
| 4… | type-specific header, then payload |
| 63 | checksum: `(0x55 - sum(bytes[0:63])) & 0xFF` |

Packet types (for transfers larger than one packet):

| t | extra header | payload offset | max payload |
|---|---|---|---|
| 0 | – | 4 | 59 |
| 1 | byte 4 = `count << 4 \| index` | 5 | 58 |
| 2 | byte 4 = count, byte 5 = index | 6 | 57 |
| 3 | bytes 4–5 = count, bytes 6–7 = index (LE) | 8 | 55 |

For reads, the packet type/count is chosen from the expected response length and one
request is sent per response chunk.

Status codes: `0` OK, `1` busy (retry after 500 ms), `2` busy (retry after 1 s), `3` not supported,
`4` device offline, `5` bad device, `6` bad data, `7` not existed, `8` no more data, `9` no space.
Error responses may carry an invalid checksum.

## Commands

Even ids write, odd ids read.

| Read | Write | Size | Content | Status |
|---|---|---|---|---|
| `0x01` | `0x00` | 2 | active trigger layer | 8k returns no data |
| `0x05` | – | 4 | change counter (increments on every stored change) | ✔ |
| `0x0D` | – | ASCII | serial / production id | ✔ |
| `0x19` | `0x18` | 26 | lighting | ✔ read + write |
| `0x1B` | `0x1A` | 276 | key map: 2 layers × 69 keys × (function, param) | read ✔, write **unverified** (see [Key map](#key-map)) |
| `0x21` | `0x20` | 216 | DKS per key | ✗ |
| `0x31` | `0x30` | 4 / key | trigger table | ✔ (see below) |
| `0x35` | `0x34` | 22 | SOCD | ✗ (read needs a request payload) |

### Lighting (`0x18` / `0x19`, 26 bytes)

| Offset | Field | Range |
|---|---|---|
| 0 | on | 0/1 |
| 1 | effect | 0 spectrum, 1 static, 2 wave, 3 breathing, 4 snake, 5 magnetic, 6 wave centre, 7 laser, 8 cross wave, 9 traffic, 10 ripple |
| 2 | brightness | 0–9 |
| 3 | speed | 0–3, **inverted**: 0 = fastest, 3 = slowest |
| 4 | active colour slot | 0–6 |
| 5–25 | 7 × RGB | |

### Trigger table (`0x30` / `0x31`)

Records of 4 bytes: `[key, 0x02, A, B]`, key = 0…68 (see `src/kb65he/layout.py`).

* Read: send records `[key, 0, 0, 0]`, the response contains the filled records.
* Write: send the records to change.
* **A** = actuation point in 0.1 mm (1…40). Verified.
* **B** = rapid-trigger distance in 0.1 mm (1…40). Verified: with A = 2.0 mm and B = 0.1 mm the
  key re-triggers after a tiny lift; with B = 4.0 mm it does not. There is no separate on/off
  flag, 4.0 mm behaves like "off". The on-keyboard adjustment mode (Fn + Tab) changed B for all keys.

The table must be read in one transfer (all 69 records); splitting the read request into single packets makes the firmware time out. Writes of any number of records work.

Firmware quirk: the read response never contains a record for the last key (68, arrow right); the bytes at that position are left over from the previous packet. Writing key 68 is accepted.


## Key map

**Firmware quirk (verified on hardware):** reading `0x1B` returns only **272** of the 276 bytes; the
last two Fn-layer entries (keys 67 and 68, Fn+Down and Fn+Right) are never reported, just like the
trigger-table read drops key 68. The tool completes the block with the value it wrote last, or the
factory default, and does not depend on those two entries when verifying a write.

**Factory default (verified on hardware):** the reset table inside the vendor software differs from
an unmodified KB65HE 8k ISO in five special entries: base `#` key `0xE3` (table: `0x16`), Fn+Tab
`0xF4` (the on-keyboard actuation adjust mode; table: plain Tab `0x09`), Fn+Ä `0xDE` (table: `0xF9`),
Fn+Space `0xF6` (table: `0xEF`), Fn on the Fn layer `0xF5` (table: `0xF7`). The tool uses the values
read from the keyboard as its factory default; writing the vendor table would disable Fn+Tab.

Status: **read and write verified on hardware** (2026-10-29: a full rewrite read back identical; Fn+G set
to Pause produced `KEY_PAUSE` on the input device while G alone still produced `KEY_G`).
Implemented in `src/kb65he/keymap.py` (CLI `kb65he keymap`, GUI page "Key map"); hardware test steps are in
[TESTPLAN-remapping.md](TESTPLAN-remapping.md).

### Block layout (`0x1B` read, `0x1A` write, 276 = 0x114 bytes)

```
offset   0 … 137   layer 0 (normal)  : 69 entries, key n at offset 2*n
offset 138 … 275   layer 1 (Fn held) : 69 entries, key n at offset 138 + 2*n
entry = [function, param]
```

Key numbers are the firmware key numbers of `src/kb65he/layout.py` (0 = Esc … 64 = Fn … 68 = →).
The whole block is always written and read in one transfer (packet type 1, 5 packets, same framing
as the trigger table). The write payload is exactly the 276 bytes, nothing else.

### What an entry is

`function` is the vendor software's `cbFunctionIndex`, `param` its `cbFunctionParam`
(`BUTTON_FUNCTION_DATA`, two bytes). For ordinary keys `function` **is the Windows virtual-key code**
(`0x41` = A, `0x70` = F1, `0x1B` = Esc), `param` is 0. So the "VK code, 0" observation from hardware and the
"function index, param" struct are the same thing: the index space is the VK space plus extra
vendor codes above/below it.

Evidence:

* The key table is cached in the native plugin as `KeyTableFN[2]`, each `KeyTable[69]` of two-byte
  entries (`DeviceUI.SDK/Device_SDK.cs`, `BUTTON_FUNCTION_DATA_2` l. 63, `PROFILE_TYPE_SOCD` l. 97,
  `BUTTON_FUNCTION_DATA` l. 261). 2 × 69 × 2 = 276 = 0x114.
* The sync routine `FUN_1800187c0` sends exactly that cache with HID command `0x1A`, length `0x114`
  (`FUN_1800187c0.c` l. 237–245, only if it differs from the last known device state; other board variants
  send `0x110` = 68 keys, `DevicePlus.c` l. 19907). There is no separate commit/save command.
  The loader `FUN_180039130` reads `0x1B` with length `0x114` (`FUN_180039130.c` l. 252–254).
* When the user picks a standard key in the vendor UI, the radio button's decimal `Tag` (a VK code) is
  stored directly: `byte num = Convert.ToByte(Tag)` → `SetKeyFunction(layer, key, num)` →
  `KeyTable[key].cbFunctionIndex = num` (`DeviceUI/DeviceSOCD.cs` l. 872–875). Media, mouse and
  lighting buttons use hex tags (l. 916, 948, 1105) in the same field.
* The daemon handler for "set key function" (code `0x1C`, `FUN_1800238a0.c` l. 228–270) copies the
  function byte into the table entry for `layer * 69 + key` (layer < 2, key < 69) and stores the
  param byte; it then triggers the sync above. Reading (`0x1D`, l. 273) returns the same byte.
* Hardware: the first bytes read from a real ISO board are `1b 00 31 00 32 00 …` (Esc, 1, 2) and the
  Fn layer starts `c0 00 70 00 71 00` (`, F1, F2).

### Layers

Layer 0 is the normal layer, layer 1 is used while Fn is held (`KEYBOARD_LAYER_LEVEL_NORMAL = 0`,
`Device_SDK.cs` l. 277; the vendor UI's "Fn layer" list selects index 1). The Fn key itself (key 64)
holds `0xF5` in layer 0 (`VK_FN` in `KeyCodeIndex.cs`).

### Function indices

| Value | Meaning | Source |
|---|---|---|
| `0x00` | none / unused | assumed, never seen in a default table |
| `0x08 0x09 0x0D 0x13 0x14 0x1B 0x20…0x28 0x2C 0x2D 0x2E` | Backspace, Tab, Enter, Pause, Caps, Esc, Space, PgUp, PgDn, End, Home, ←↑→↓, PrtSc, Ins, Del (Windows VK) | vendor UI `BtnShow`, default table ✔ |
| `0x30…0x39`, `0x41…0x5A` | `0`…`9`, `A`…`Z` (VK = ASCII). Letters name the **US** legend; the OS layout decides the typed character | ✔ |
| `0x5B 0x5C 0x5D` | Left Win, Right Win, Menu | ✔ |
| `0x60…0x69`, `0x6A 0x6B 0x6C 0x6D 0x6E 0x6F` | numpad 0–9, `*`, `+`, separator (Enter), `-`, `.`, `/` | vendor UI |
| `0x70…0x7B` | F1…F12 | ✔ |
| `0x90 0x91` | Num Lock, Scroll Lock | vendor UI |
| `0xA0…0xA5` | L/R Shift, L/R Ctrl, L/R Alt (AltGr = `0xA5`) | ✔ |
| `0xBA 0xBB 0xBC 0xBD 0xBE 0xBF 0xC0 0xDB 0xDC 0xDD 0xDE` | `;` `=` `,` `-` `.` `/` `` ` `` `[` `\` `]` `'` (VK_OEM_*, US legend) | ✔ |
| `0xE2` | ISO `<` key (VK_OEM_102), default of key 45 | default table; not offered in the vendor UI |
| `0x16` | default of key 41 (ISO `#`), meaning unknown | default table only |
| `0x01 0x02 0x04 0x05 0x06` | mouse left, right, middle, back (XButton1), forward (XButton2) | vendor UI `GetFunctionName` |
| `0xAD 0xAE 0xAF 0xB0 0xB1 0xB3 0xB5` | mute, vol−, vol+, next, previous, play/pause, media player | vendor UI; vol± seen in Fn layer ✔ |
| `0x94 0x95` | lighting effect, lighting colour | vendor UI; seen on Fn+S / Fn+W ✔ |
| `0xCC 0xCD 0xCE 0xCF` | brightness +, brightness −, speed +, speed − | vendor UI; seen on Fn+D/A/E/Q ✔ |
| `0xF5` | Fn | default table |
| `0x98` (152) | macro; `param` = `layer*69 + key` (decompiled) | vendor UI, `FUN_1800238a0.c` l. 266. Macro body lives elsewhere |
| `0x9A` (154) | key combination | vendor UI (`VK_ACCELERATOR`) |
| `0xD9`, `0xDA` (217, 218) | DKS; `param` = DKS slot 0…19 allocated by the plugin (decompiled, l. 302–345) | vendor UI |
| `0xF9 0xE3 0xEF 0xF7` | present in the default Fn layer (Fn+', Fn+#, Fn+Space, Fn+AltGr …), meaning unknown | default table |

"✔" = appears with that meaning in the default table that matches a real keyboard's read-out and in the
vendor code. Anything without a ✔ is taken from the vendor software only. "Disabled key" is **not**
a function the vendor UI offers; whether `0x00` disables a key is untested.

`param` is 0 for every simple function. For macro and DKS entries it references data stored elsewhere on
the keyboard, therefore `kb65he` never edits or overwrites such entries.

### Factory default and reset

The vendor plugin has no dedicated "reset keys" HID command. "Restore factory" is daemon code 9
(`DeviceApi_RestoreFactory(id, what)`; `what` = 1 keys, 2 lighting, 3 trigger table, 4 SOCD; the vendor UI
calls it from `DeviceSOCD.cs` l. 2457, 2871, 2881, 3529). For `what = 1` (`FUN_1800238a0.c` l. 119–146)
the plugin overwrites its cached key table with a built-in default, clears the macro cache and DKS slots, then
syncs, i.e. it sends the default via the ordinary `0x1A` write (plus the DKS clear via `0x20`).

The built-in default is two 138-byte tables at `DevicePlus.dll` virtual addresses `0x1800b6090` (layer 0)
and `0x1800b6120` (layer 1). They are embedded as `DEFAULT_HEX` in `src/kb65he/keymap.py`; the start of both
layers is identical to what a real keyboard returned. Whether the *whole* table equals what the
keyboard shipped with has not been compared on hardware yet (step 1 of the test plan does that).

### Safety rules implemented in `kb65he`

* Every write is validated against the current key map: only entries that are known targets
  (standard, media, lighting, mouse) with `param = 0`, or the factory default of that position, may change;
  all other entries are byte-for-byte preserved. Macro/combo/DKS entries are never overwritten, and the
  Fn key (layer 0, key 64) cannot be remapped.
* A profile backup (`~/.config/kb65he/backups/keymap-<timestamp>.json`) is saved before every write, and
  the write is always followed by a read-back and a comparison; on a mismatch the previous table is written
  back once and an error is raised.

### Open questions

* Answered: the keyboard accepts the `0x1A` write with status byte `0`, and a remapped key works at
  once, without re-enumeration.
* What do `0x00` and the unknown firmware codes (`0x16`, `0xF9`, `0xE3`, `0xEF`, `0xF7`) do?
* Does the firmware validate the table (e.g. refuse a missing Fn key)?

## Pushed reports (from the vendor software, not yet seen on Linux)

The Windows software treats an input report whose first byte (report id) is `0x04` as an event;
`byte 1` is the event code and `byte 3` the value (`byte 7` for SOCD): `0x94` lighting effect, `0x95` colour slot,
`0x96` brightness, `0x97` speed, `0x9C` SOCD, `0x9E` profile/layer switch, `0x9F` trigger
distances changed on the keyboard (`0x98`–`0x9B`, `0x9D` are ignored by the vendor UI). They
announce settings changed with Fn shortcuts; none carries key positions. Which hidraw node
delivers them on Linux is not confirmed yet (likely the report-id-3/4 interface). Details and evidence:
[RESEARCH-key-depth.md](RESEARCH-key-depth.md).

### Unknown command ids

The firmware does not answer unknown command ids at all (no `NOT_SUPPORTED`, just silence). After
roughly two dozen unanswered requests the keyboard dropped off the bus and had to be replugged; the
trigger table was reset to defaults (without changing the counter). Do not send unknown ids in bulk.
