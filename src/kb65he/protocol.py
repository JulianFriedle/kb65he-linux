"""Packet framing for the KB65HE 8k vendor HID interface.

Every transfer is a 64-byte report on the vendor interface (usage page 0xFF01)
without a report ID:

    byte 0      0x00
    byte 1      bits 0-5: command id, bits 6-7: packet type (0..3)
    byte 2      0 in requests, status code in responses
    byte 3      length = payload bytes + header extra (type 0:+0, 1:+1, 2:+2, 3:+4)
    type 0      payload at byte 4 (max 59 bytes)
    type 1      byte 4 = (count << 4) | index, payload at byte 5 (max 58)
    type 2      byte 4 = count, byte 5 = index, payload at byte 6 (max 57)
    type 3      bytes 4-5 = count (LE), bytes 6-7 = index (LE), payload at byte 8 (max 55)
    byte 63     checksum = (0x55 - sum(bytes 0..62)) & 0xFF

Each request packet is answered by exactly one response packet carrying the
same command id. Even command ids write, odd ids read.
"""
from __future__ import annotations

from dataclasses import dataclass

PACKET_SIZE = 64

HEADER_EXTRA = {0: 0, 1: 1, 2: 2, 3: 4}
DATA_OFFSET = {0: 4, 1: 5, 2: 6, 3: 8}
MAX_CHUNK = {0: 59, 1: 58, 2: 57, 3: 55}

STATUS_OK = 0
STATUS_NAMES = {
    0: "OK",
    1: "BUSY",
    2: "BUSY_LONG",
    3: "NOT_SUPPORTED",
    4: "DEVICE_OFFLINE",
    5: "BAD_DEVICE",
    6: "BAD_DATA",
    7: "DEVICE_NOT_EXISTED",
    8: "NO_MORE_DATA",
    9: "NO_SPACE",
}


class Cmd:
    SET_LAYER = 0x00
    GET_LAYER = 0x01
    GET_REVISION = 0x05      # 4 bytes, increments on every stored change
    GET_SERIAL = 0x0D        # ASCII
    SET_LIGHTING = 0x18      # 26 bytes
    GET_LIGHTING = 0x19
    SET_KEYMAP = 0x1A
    GET_KEYMAP = 0x1B        # 69 x 4 bytes (two layers of 2-byte entries)
    SET_DKS = 0x20
    GET_DKS = 0x21
    SET_TRIGGER = 0x30       # records [key, 2, actuation, b]
    GET_TRIGGER = 0x31
    SET_SOCD = 0x34
    GET_SOCD = 0x35


class ProtocolError(IOError):
    pass


class DeviceStatusError(ProtocolError):
    def __init__(self, cmd: int, status: int):
        self.cmd = cmd
        self.status = status
        super().__init__(f"command 0x{cmd:02X} failed: {STATUS_NAMES.get(status, status)}")


def checksum(first63: bytes) -> int:
    return (0x55 - sum(first63)) & 0xFF


def choose_type(total: int) -> tuple[int, int]:
    """Return (packet type, packet count) for a transfer of `total` bytes."""
    if total <= MAX_CHUNK[0]:
        return 0, 1
    n = (total - 1) // MAX_CHUNK[1] + 1
    if n <= 0xF:
        return 1, n
    n = (total - 1) // MAX_CHUNK[2] + 1
    if n <= 0xFF:
        return 2, n
    return 3, (total - 1) // MAX_CHUNK[3] + 1


def build_packets(cmd: int, payload: bytes = b"", total: int | None = None) -> list[bytes]:
    """Split `payload` into request packets.

    `total` selects the packet type/count. For reads it is the expected response
    length; for writes it defaults to len(payload).
    """
    if total is None:
        total = len(payload)
    ptype, count = choose_type(max(total, len(payload)))
    chunk = MAX_CHUNK[ptype]
    packets = []
    for idx in range(count):
        part = payload[idx * chunk:(idx + 1) * chunk]
        p = bytearray(PACKET_SIZE)
        p[1] = (cmd & 0x3F) | (ptype << 6)
        p[3] = len(part) + HEADER_EXTRA[ptype]
        if ptype == 1:
            p[4] = ((count & 0xF) << 4) | (idx & 0xF)
        elif ptype == 2:
            p[4] = count & 0xFF
            p[5] = idx & 0xFF
        elif ptype == 3:
            p[4:6] = count.to_bytes(2, "little")
            p[6:8] = idx.to_bytes(2, "little")
        off = DATA_OFFSET[ptype]
        p[off:off + len(part)] = part
        p[63] = checksum(p[:63])
        packets.append(bytes(p))
    return packets


@dataclass
class Response:
    cmd: int
    status: int
    data: bytes


def parse_response(packet: bytes) -> Response:
    if len(packet) != PACKET_SIZE:
        raise ProtocolError(f"expected {PACKET_SIZE} bytes, got {len(packet)}")
    cmd = packet[1] & 0x3F
    status = packet[2]
    if status not in (0, 1, 2):
        # error responses do not always carry a valid checksum
        return Response(cmd, status, b"")
    if packet[63] != checksum(packet[:63]):
        raise ProtocolError("bad response checksum: " + packet.hex(" "))
    ptype = packet[1] >> 6
    length = max(0, min(packet[3] - HEADER_EXTRA[ptype], MAX_CHUNK[ptype]))
    off = DATA_OFFSET[ptype]
    return Response(cmd, status, bytes(packet[off:off + length]))
