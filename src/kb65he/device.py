"""Device discovery, hidraw transport and the high-level keyboard API."""
from __future__ import annotations

import glob
import os
import select
import time
from dataclasses import dataclass, field

from .keymap import (
    DEFAULT_KEYMAP,
    KEYMAP_SIZE,
    TARGETS,
    Entry,
    ExperimentalDisabled,
    Keymap,
    KeymapError,
    KeymapVerifyError,
    parse_target,
    validate_change,
)
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
RT_OFF = 4.0           # rapid-trigger distance that behaves like "off"
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
    speed: int = 1  # 0 = slowest .. SPEED_MAX = fastest (inverted on the wire)
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
        # the firmware stores 0 = fastest, SPEED_MAX = slowest
        speed = SPEED_MAX - min(b[3], SPEED_MAX)
        return cls(bool(b[0]), b[1], b[2], speed, b[4], colors)  # type: ignore[arg-type]

    def to_bytes(self) -> bytes:
        raw_speed = SPEED_MAX - max(0, min(self.speed, SPEED_MAX))
        out = bytearray([int(self.on), self.effect, self.brightness, raw_speed, self.color_index])
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
        """Raw key map block (276 bytes, see :mod:`kb65he.keymap`)."""
        return self.get(Cmd.GET_KEYMAP, KEYMAP_SIZE)

    # key map (remapping) - writing is EXPERIMENTAL ---------------------------
    def read_keymap(self) -> Keymap:
        # the firmware never reports the last 4 bytes (Fn+Down, Fn+Right); use what we
        # wrote last, otherwise the factory default (see Keymap.from_bytes)
        return Keymap.from_bytes(self.keymap(), getattr(self, "_keymap_tail", None))

    def write_keymap(self, keymap: Keymap, *, experimental: bool = False,
                     before_write=None) -> Keymap:
        """Write a key map, read it back and compare. EXPERIMENTAL.

        Nothing is sent unless ``experimental=True``. The change is validated against
        the current key map first (:func:`kb65he.keymap.validate_change`).
        ``before_write(current)`` is called after validation and right before the
        write; if it raises, nothing is written (used for the automatic backup).

        If the read-back differs (or the write/read fails) the previous key map is
        written back once, and the error is raised. Returns the verified key map.
        """
        if not experimental:
            raise ExperimentalDisabled(
                "writing the key map is experimental and has not been verified on hardware - "
                "pass experimental=True / --experimental to confirm")
        if not isinstance(keymap, Keymap):
            raise TypeError("keymap must be a Keymap")
        current = self.read_keymap()
        validate_change(current, keymap)
        if before_write is not None:
            before_write(current)
        try:
            self.set(Cmd.SET_KEYMAP, keymap.to_bytes())
            self._keymap_tail = keymap.to_bytes()[-4:]
            after = self.read_keymap()
        except Exception:
            self._rollback_keymap(current)
            raise
        if after != keymap:
            restored = self._rollback_keymap(current)
            diffs = ", ".join(f"layer {l} key {k}: wrote {w.function:#04x}/{w.param:#04x}, "
                              f"read {r.function:#04x}/{r.param:#04x}"
                              for l, k, w, r in keymap.diff(after)[:5])
            raise KeymapVerifyError(
                "key map read-back differs from what was written (" + diffs + "); "
                + ("the previous key map was restored and verified" if restored
                   else "RESTORING THE PREVIOUS KEY MAP FAILED - restore your backup, see "
                        "docs/TESTPLAN-remapping.md"))
        return after

    def _rollback_keymap(self, previous: Keymap) -> bool:
        try:
            self.set(Cmd.SET_KEYMAP, previous.to_bytes())
            self._keymap_tail = previous.to_bytes()[-4:]
            return self.read_keymap() == previous
        except Exception:  # noqa: BLE001 - best effort, the original error is raised
            return False

    def remap_key(self, key: int, target, *, layer: int = 0, experimental: bool = False,
                  before_write=None) -> Keymap:
        """Assign a standard key / media / lighting / mouse function to one key. EXPERIMENTAL.

        `target` is a name like ``"F5"`` or ``"volup"`` (see :func:`kb65he.keymap.parse_target`)
        or a function index from :data:`kb65he.keymap.TARGETS`. `layer` 0 = normal, 1 = Fn.
        """
        if not experimental:
            raise ExperimentalDisabled(
                "remapping is experimental and has not been verified on hardware - "
                "pass experimental=True / --experimental to confirm")
        if isinstance(target, int):
            if target not in TARGETS:
                raise KeymapError(f"unsupported target {target:#04x}")
            function = target
        else:
            function = parse_target(str(target))
        current = self.read_keymap()
        new = current.with_entry(layer, key, Entry(function, 0))
        return self.write_keymap(new, experimental=True, before_write=before_write)

    def reset_keymap(self, *, experimental: bool = False, before_write=None) -> Keymap:
        """Write the factory default key map (both layers). EXPERIMENTAL."""
        return self.write_keymap(DEFAULT_KEYMAP, experimental=experimental,
                                 before_write=before_write)

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

    def read_rapid_trigger(self) -> dict[int, float]:
        """Rapid-trigger distance per key in mm (4.0 = effectively off)."""
        return {k: b / 10 for k, (_, b) in self.read_trigger().items()}

    def write_trigger(self, values: dict[int, tuple[float | None, float | None]]) -> None:
        """values: {key: (actuation_mm, rapid_trigger_mm)}; None keeps the current value."""
        current = self.read_trigger()
        records = []
        for key, (act, rt) in sorted(values.items()):
            if not 0 <= key < NUM_KEYS:
                raise ValueError(f"key {key} out of range")
            cur_a, cur_b = current.get(key, (10, 2))
            a = cur_a if act is None else round(act * 10)
            b = cur_b if rt is None else round(rt * 10)
            for v, name in ((a, "actuation"), (b, "rapid trigger")):
                if not ACTUATION_MIN <= v <= ACTUATION_MAX:
                    raise ValueError(f"{name} {v / 10} mm out of range 0.1..4.0")
            records.append(bytes([key, 2, a, b]))
        self.set(Cmd.SET_TRIGGER, b"".join(records))
        for r in records:
            self._written[r[0]] = (r[2], r[3])

    def write_actuation(self, values: dict[int, float]) -> None:
        self.write_trigger({k: (mm, None) for k, mm in values.items()})

    def write_rapid_trigger(self, values: dict[int, float]) -> None:
        self.write_trigger({k: (None, mm) for k, mm in values.items()})


class FakeTransport:
    """In-memory keyboard used by `--demo` and the tests."""

    def __init__(self):
        self.lighting = bytearray(Lighting(effect=2, color_index=1).to_bytes())
        self.trigger = {k: [10, 2] for k in range(NUM_KEYS)}
        for k in (17, 30, 31, 32):  # W A S D
            self.trigger[k][0] = 4
        self.revision = 0x2C
        self.keymap = bytearray(DEFAULT_KEYMAP.to_bytes())
        self.keymap_writes: list[bytes] = []   # every accepted 0x1A payload, for tests
        self.keymap_corrupt_next = 0           # store garbage for the next N accepted writes
        self.keymap_reject = False             # simulate a keyboard that answers BAD_DATA

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
        if cmd in (Cmd.GET_TRIGGER, Cmd.SET_TRIGGER, Cmd.GET_KEYMAP, Cmd.SET_KEYMAP):
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
            if cmd == Cmd.SET_KEYMAP:
                if idx == count - 1:
                    if self.keymap_reject or len(self._buf) != KEYMAP_SIZE:
                        raise DeviceStatusError(cmd, 6)
                    self.keymap_writes.append(bytes(self._buf))
                    self.keymap[:] = self._buf
                    if self.keymap_corrupt_next > 0:
                        self.keymap_corrupt_next -= 1
                        self.keymap[0] ^= 0xFF
                    self.revision += 1
                return b""
            if cmd == Cmd.GET_KEYMAP:
                full = bytes(self.keymap)[:-4]  # like the real firmware: last 4 bytes missing
            else:
                full = b"".join(bytes([k, 2, *self.trigger[k]]) for k in range(NUM_KEYS))
            chunk = MAX_CHUNK[ptype]
            return full[idx * chunk:(idx + 1) * chunk]
        if cmd == Cmd.GET_SERIAL:
            return b"DEMO0000000000000"
        if cmd == Cmd.GET_REVISION:
            return self.revision.to_bytes(4, "little")
        return b""
