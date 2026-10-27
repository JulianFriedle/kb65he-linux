"""Device discovery, hidraw transport and the high-level keyboard API."""
from __future__ import annotations

import glob
import os
import select
import time
from dataclasses import dataclass, field

from .protocol import (
    Cmd,
    DeviceStatusError,
    ProtocolError,
    build_packets,
    parse_response,
)

VENDOR_ID = 0x3367
SUPPORTED = {0x5035: "KB65HE 8k (ISO)"}
EXPERIMENTAL = {0x5036: "KB65HE 8k (ANSI)"}
BOOTLOADER = {0x5033, 0x5034}
VENDOR_DESCRIPTOR_PREFIX = b"\x06\x01\xff"   # Usage Page (0xFF01)

NUM_KEYS = 69
ACTUATION_MIN = 1      # 0.1 mm
ACTUATION_MAX = 40     # 4.0 mm
RECORDS_PER_PACKET = 14  # 14 x 4 bytes fit in a single packet

LIGHT_EFFECTS = [
    "spectral_cycle", "static", "surf_left", "breathing", "snake", "magnetic",
    "surf_mid", "laser", "cross_surf", "traffic", "ripple",
]
BRIGHTNESS_MAX = 9
SPEED_MAX = 3


class DeviceNotFound(IOError):
    pass


class BootloaderMode(IOError):
    pass


@dataclass
class DeviceInfo:
    path: str
    product_id: int

    @property
    def name(self) -> str:
        return SUPPORTED.get(self.product_id) or EXPERIMENTAL.get(self.product_id, "unknown")


def _hid_id(uevent: str) -> tuple[int, int] | None:
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            _, vid, pid = line.split("=", 1)[1].split(":")
            return int(vid, 16), int(pid, 16)
    return None


def find_devices(sysfs: str = "/sys/class/hidraw") -> list[DeviceInfo]:
    found = []
    for desc in sorted(glob.glob(os.path.join(sysfs, "hidraw*", "device", "report_descriptor"))):
        devdir = os.path.dirname(desc)
        try:
            with open(os.path.join(devdir, "uevent")) as f:
                ids = _hid_id(f.read())
            if not ids or ids[0] != VENDOR_ID:
                continue
            if ids[1] in BOOTLOADER:
                raise BootloaderMode("keyboard is in bootloader mode - not touching it")
            if ids[1] not in SUPPORTED and ids[1] not in EXPERIMENTAL:
                continue
            with open(desc, "rb") as f:
                if not f.read().startswith(VENDOR_DESCRIPTOR_PREFIX):
                    continue
        except OSError:
            continue
        node = desc.split(os.sep)[-3]
        found.append(DeviceInfo(f"/dev/{node}", ids[1]))
    return found


class HidrawTransport:
    def __init__(self, path: str, timeout: float = 2.0, verbose: bool = False):
        self.path = path
        self.timeout = timeout
        self.verbose = verbose
        self.fd = os.open(path, os.O_RDWR)
        self._drain()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _drain(self):
        while select.select([self.fd], [], [], 0.02)[0]:
            os.read(self.fd, 64)

    def transact(self, packet: bytes, retries: int = 5) -> bytes:
        cmd = packet[1] & 0x3F
        for _ in range(retries):
            if self.verbose:
                print(">>", packet.hex(" "))
            os.write(self.fd, b"\x00" + packet)  # leading 0 = no report id
            deadline = time.monotonic() + self.timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                    raise TimeoutError(f"timeout waiting for command 0x{cmd:02X}")
                raw = os.read(self.fd, 64)
                if self.verbose:
                    print("<<", raw.hex(" "))
                resp = parse_response(raw)
                if resp.cmd != cmd:
                    continue
                if resp.status in (1, 2):
                    time.sleep(0.5 if resp.status == 1 else 1.0)
                    break
                if resp.status != 0:
                    raise DeviceStatusError(cmd, resp.status)
                return resp.data
        raise ProtocolError(f"device stayed busy for command 0x{cmd:02X}")


@dataclass
class Lighting:
    on: bool = True
    effect: int = 1
    brightness: int = 9
    speed: int = 2
    color_index: int = 0
    colors: list[tuple[int, int, int]] = field(default_factory=lambda: [
        (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (255, 255, 0), (255, 0, 255), (0, 255, 255)])

    SIZE = 26

    @classmethod
    def from_bytes(cls, b: bytes) -> "Lighting":
        if len(b) < cls.SIZE:
            raise ProtocolError(f"lighting block too short ({len(b)} bytes)")
        colors = [tuple(b[5 + 3 * i:8 + 3 * i]) for i in range(7)]
        return cls(bool(b[0]), b[1], b[2], b[3], b[4], colors)  # type: ignore[arg-type]

    def to_bytes(self) -> bytes:
        out = bytearray([int(self.on), self.effect, self.brightness, self.speed, self.color_index])
        for r, g, b in self.colors[:7]:
            out += bytes([r & 0xFF, g & 0xFF, b & 0xFF])
        return bytes(out)


class KB65HE:
    """High-level API. `transport` needs a `transact(packet) -> bytes` method."""

    def __init__(self, transport, info: DeviceInfo | None = None):
        self.t = transport
        self.info = info
        # The firmware does not report the last key (68) when reading the trigger
        # table, so remember what we wrote.
        self._written: dict[int, tuple[int, int]] = {}

    @classmethod
    def open(cls, verbose: bool = False) -> "KB65HE":
        devices = find_devices()
        if not devices:
            raise DeviceNotFound("no KB65HE 8k found")
        dev = devices[0]
        return cls(HidrawTransport(dev.path, verbose=verbose), dev)

    def close(self):
        close = getattr(self.t, "close", None)
        if close:
            close()

    # generic -----------------------------------------------------------
    def get(self, cmd: int, length: int, payload: bytes = b"") -> bytes:
        out = bytearray()
        for p in build_packets(cmd, payload, max(length, len(payload))):
            out += self.t.transact(p)
        return bytes(out[:length])

    def set(self, cmd: int, payload: bytes) -> None:
        for p in build_packets(cmd, payload):
            self.t.transact(p)

    # info --------------------------------------------------------------
    def serial(self) -> str:
        return self.get(Cmd.GET_SERIAL, 33).rstrip(b"\x00").decode("ascii", "replace")

    def revision(self) -> int:
        return int.from_bytes(self.get(Cmd.GET_REVISION, 20)[:4], "little")

    def keymap(self) -> bytes:
        return self.get(Cmd.GET_KEYMAP, NUM_KEYS * 4)

    # lighting ----------------------------------------------------------
    def read_lighting(self) -> Lighting:
        return Lighting.from_bytes(self.get(Cmd.GET_LIGHTING, Lighting.SIZE))

    def write_lighting(self, lighting: Lighting) -> None:
        self.set(Cmd.SET_LIGHTING, lighting.to_bytes())

    # trigger / actuation -------------------------------------------------
    def read_trigger(self) -> dict[int, tuple[int, int]]:
        """Return {key: (actuation, b)}; actuation in 0.1 mm, b not yet decoded."""
        # The firmware only answers a request for the whole table (one multi-packet
        # transfer); splitting it into single packets times out.
        result: dict[int, tuple[int, int]] = {}
        req = b"".join(bytes([k, 0, 0, 0]) for k in range(NUM_KEYS))
        data = self.get(Cmd.GET_TRIGGER, len(req), req)
        for i in range(0, len(data) - 3, 4):
            k, kind, a, b = data[i:i + 4]
            if kind == 2 and k < NUM_KEYS and k not in result:
                result[k] = (a, b)
        for k, v in self._written.items():
            result.setdefault(k, v)
        return result

    def read_actuation(self) -> dict[int, float]:
        return {k: a / 10 for k, (a, _) in self.read_trigger().items()}

    def write_actuation(self, values: dict[int, float]) -> None:
        """values: {key: millimetres}. The second (undecoded) byte is preserved."""
        current = self.read_trigger()
        records = []
        for key, mm in sorted(values.items()):
            if not 0 <= key < NUM_KEYS:
                raise ValueError(f"key {key} out of range")
            raw = round(mm * 10)
            if not ACTUATION_MIN <= raw <= ACTUATION_MAX:
                raise ValueError(f"actuation {mm} mm out of range 0.1..4.0")
            b = current.get(key, (10, 2))[1]
            records.append(bytes([key, 2, raw, b]))
        self.set(Cmd.SET_TRIGGER, b"".join(records))
        for r in records:
            self._written[r[0]] = (r[2], r[3])


class FakeTransport:
    """In-memory keyboard used by `--demo` and the tests."""

    def __init__(self):
        self.lighting = bytearray(Lighting(effect=2, color_index=1).to_bytes())
        self.trigger = {k: [10, 2] for k in range(NUM_KEYS)}
        for k in (17, 30, 31, 32):  # W A S D
            self.trigger[k][0] = 4
        self.revision = 0x2C

    def transact(self, packet: bytes) -> bytes:
        from .protocol import DATA_OFFSET, HEADER_EXTRA
        cmd = packet[1] & 0x3F
        ptype = packet[1] >> 6
        data = packet[DATA_OFFSET[ptype]:DATA_OFFSET[ptype] + packet[3] - HEADER_EXTRA[ptype]]
        if cmd == Cmd.GET_LIGHTING:
            return bytes(self.lighting)
        if cmd == Cmd.SET_LIGHTING:
            self.lighting[:] = data[:26]
            self.revision += 1
            return b""
        if cmd in (Cmd.GET_TRIGGER, Cmd.SET_TRIGGER):
            # multi-packet: collect the request, answer chunk by chunk
            from .protocol import MAX_CHUNK
            idx, count = {
                0: (0, 1),
                1: (packet[4] & 0xF, packet[4] >> 4),
                2: (packet[5], packet[4]),
                3: (int.from_bytes(packet[6:8], "little"), int.from_bytes(packet[4:6], "little")),
            }[ptype]
            if idx == 0:
                self._buf = bytearray()
            self._buf += data
            if cmd == Cmd.SET_TRIGGER:
                if idx == count - 1:
                    for i in range(0, len(self._buf) - 3, 4):
                        self.trigger[self._buf[i]] = [self._buf[i + 2], self._buf[i + 3]]
                    self.revision += 1
                return b""
            full = b"".join(bytes([k, 2, *self.trigger[k]]) for k in range(NUM_KEYS))
            chunk = MAX_CHUNK[ptype]
            return full[idx * chunk:(idx + 1) * chunk]
        if cmd == Cmd.GET_SERIAL:
            return b"DEMO0000000000000"
        if cmd == Cmd.GET_REVISION:
            return self.revision.to_bytes(4, "little")
        return b""
