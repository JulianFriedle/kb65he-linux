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
| `0x1B` | `0x1A` | 276 | key map, 2 bytes per key (Windows VK code, 0), base + Fn layer | read ✔ |
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

## Pushed reports (from the vendor software, not yet seen on Linux)

The Windows software treats an input report whose first byte (report id) is `0x04` as an event;
`byte 1` is the event code and `byte 3` the value (`byte 7` for SOCD): `0x94` lighting effect, `0x95` colour slot,
`0x96` brightness, `0x97` speed, `0x9C` SOCD, `0x9E` profile/layer switch, `0x9F` trigger
distances changed on the keyboard (`0x98`–`0x9B`, `0x9D` are ignored by the vendor UI). They
announce settings changed with Fn shortcuts; none carries key positions. Which hidraw node
delivers them is unknown; `kb65he probe --watch` listens on all of them. Details and evidence:
[RESEARCH-key-depth.md](RESEARCH-key-depth.md).
