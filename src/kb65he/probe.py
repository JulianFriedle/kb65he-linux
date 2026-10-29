"""Read-only probe for undocumented keyboard features (issue #3: live key depth).

The probe answers one question on real hardware: does the firmware expose analog
key travel (or anything else we do not know yet) through the vendor HID interface?

Safety rules, all enforced in code:

* Only *read* commands are ever sent: odd command ids, an empty payload, a single
  64-byte packet. ``check_read_only_packet`` rejects everything else, and it is
  called twice (in ``ReadOnlyLink`` and again right before the hidraw write).
* One request per command id, short timeout, no retries.
* ``watch`` opens the hidraw nodes read-only (``O_RDONLY``), it cannot write at all.
* Even ids (writes) cannot be selected: not from the CLI, not from the API.
"""
from __future__ import annotations

import errno
import json
import os
import platform
import select
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .protocol import (
    DATA_OFFSET,
    HEADER_EXTRA,
    MAX_CHUNK,
    PACKET_SIZE,
    STATUS_NAMES,
    build_packets,
    checksum,
)

# read commands the vendor software uses (docs/PROTOCOL.md); not probed again
KNOWN_READS = {0x01, 0x05, 0x0D, 0x19, 0x1B, 0x21, 0x31, 0x35}
# harmless known read, used before and after the scan to see that the keyboard still answers
CONTROL_CMD = 0x05
# everything else that can be a read command: odd ids 0x01..0x3F
DEFAULT_IDS = [c for c in range(1, 0x40, 2) if c not in KNOWN_READS]

# pushed input reports (report id 4, byte 1 = event code), see docs/RESEARCH-key-depth.md
EVENT_NAMES = {
    0x94: "lighting effect changed (byte 3 = effect)",
    0x95: "colour slot changed (byte 3 = slot)",
    0x96: "brightness changed (byte 3 = level)",
    0x97: "speed changed (byte 3 = level)",
    0x98: "reserved (ignored by the vendor UI)",
    0x99: "reserved (ignored by the vendor UI)",
    0x9A: "reserved (ignored by the vendor UI)",
    0x9B: "reserved (ignored by the vendor UI)",
    0x9C: "SOCD changed (byte 7 = state)",
    0x9D: "reserved (ignored by the vendor UI)",
    0x9E: "profile / layer switched",
    0x9F: "trigger distances changed on the keyboard",
}


class UnsafeCommand(ValueError):
    """Raised when something other than an empty read request would be sent."""


def is_read_cmd(cmd: int) -> bool:
    return isinstance(cmd, int) and not isinstance(cmd, bool) and 0 < cmd <= 0x3F and cmd & 1 == 1


def build_read_request(cmd: int) -> bytes:
    """The one packet the probe may send: read command `cmd`, no payload."""
    if not is_read_cmd(cmd):
        raise UnsafeCommand(f"command {cmd!r} is not a read command (odd id 0x01..0x3F) - refusing")
    return build_packets(cmd, b"", 0)[0]


def check_read_only_packet(packet: bytes) -> None:
    """Hard check on the raw packet: only an empty, single-packet read request passes."""
    if len(packet) != PACKET_SIZE:
        raise UnsafeCommand(f"packet has {len(packet)} bytes, expected {PACKET_SIZE}")
    cmd = packet[1] & 0x3F
    if packet[0] != 0 or packet[1] >> 6 != 0:
        raise UnsafeCommand("only single-packet requests (type 0, report id 0) are allowed")
    if not is_read_cmd(cmd):
        raise UnsafeCommand(f"command 0x{cmd:02X} is a write or reserved id - refusing")
    if packet[2] != 0 or packet[3] != 0 or any(packet[4:63]):
        raise UnsafeCommand("probe requests must not carry a payload")
    if packet[63] != checksum(packet[:63]):
        raise UnsafeCommand("bad request checksum")


def parse_ids(text: str) -> list[int]:
    """'0x03,0x07,9' -> [3, 7, 9]; raises UnsafeCommand for even or out-of-range ids."""
    ids: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            cmd = int(part, 0)
        except ValueError:
            raise ValueError(f"not a number: {part!r}") from None
        if not is_read_cmd(cmd):
            raise UnsafeCommand(f"0x{cmd:02X} is not an odd id in 0x01..0x3F - only read commands are allowed")
        if cmd not in ids:
            ids.append(cmd)
    if not ids:
        raise ValueError("no command ids given")
    return ids


# ---------------------------------------------------------------- response analysis
def analyse_response(raw: bytes) -> dict:
    """Describe a 64-byte response without raising, whatever it contains."""
    info: dict = {"raw": raw.hex(" "), "size": len(raw)}
    if len(raw) != PACKET_SIZE:
        info["problem"] = f"unexpected size {len(raw)}"
        return info
    ptype = raw[1] >> 6
    status = raw[2]
    length = max(0, min(raw[3] - HEADER_EXTRA[ptype], MAX_CHUNK[ptype]))
    off = DATA_OFFSET[ptype]
    info.update(
        cmd=raw[1] & 0x3F,
        packet_type=ptype,
        status=status,
        status_name=STATUS_NAMES.get(status, f"UNKNOWN_{status}"),
        length=length,
        checksum_ok=raw[63] == checksum(raw[:63]),
        data=raw[off:off + length].hex(" "),
    )
    return info


def classify(info: dict | None) -> str:
    """One word per probed command: data / empty / status / bad-checksum / timeout / odd."""
    if info is None:
        return "timeout"
    if "problem" in info:
        return "odd"
    if info["status"] != 0:
        return "status:" + info["status_name"]
    if not info["checksum_ok"]:
        return "bad-checksum"
    return "data" if info["length"] else "empty"


# ---------------------------------------------------------------- devices
@dataclass
class Exchange:
    response: bytes | None
    stray: list[bytes] = field(default_factory=list)   # other packets seen while waiting
    elapsed: float = 0.0


class HidrawProbeDevice:
    """Raw hidraw access for exactly one request/response exchange at a time."""

    def __init__(self, path: str, verbose: bool = False):
        self.path = path
        self.verbose = verbose
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _read_all(self, wait: float) -> list[bytes]:
        out = []
        while select.select([self.fd], [], [], wait)[0]:
            try:
                out.append(os.read(self.fd, 256))
            except BlockingIOError:
                break
            wait = 0
        return out

    def exchange(self, packet: bytes, timeout: float) -> Exchange:
        check_read_only_packet(packet)           # second, independent check
        cmd = packet[1] & 0x3F
        stray = self._read_all(0)                # anything pending is not our answer
        if self.verbose:
            print(">>", packet.hex(" "))
        os.write(self.fd, b"\x00" + packet)
        t0 = time.monotonic()
        deadline = t0 + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return Exchange(None, stray, time.monotonic() - t0)
            for raw in self._read_all(left):
                if self.verbose:
                    print("<<", raw.hex(" "))
                if len(raw) == PACKET_SIZE and raw[1] & 0x3F == cmd:
                    return Exchange(raw, stray, time.monotonic() - t0)
                stray.append(raw)


class FakeProbeDevice:
    """In-memory keyboard for tests and ``--demo``.

    `answers` maps a command id to: bytes (payload, status 0), an int (error status,
    sent without a valid checksum like the real firmware does), a callable
    ``f(n) -> bytes`` (n-th request for this id) or ``None`` (no answer).
    """

    def __init__(self, answers: dict | None = None):
        self.answers = answers if answers is not None else {
            0x05: bytes([0x2C, 0, 0, 0]) + bytes(16),
            0x07: 3,
            0x0B: bytes.fromhex("01 02 03 04"),
        }
        self.sent: list[bytes] = []
        self.counts: dict[int, int] = {}

    def close(self):
        pass

    def exchange(self, packet: bytes, timeout: float) -> Exchange:
        check_read_only_packet(packet)
        self.sent.append(packet)
        cmd = packet[1] & 0x3F
        n = self.counts[cmd] = self.counts.get(cmd, 0) + 1
        ans = self.answers.get(cmd)
        if callable(ans):
            ans = ans(n)
        if ans is None:
            return Exchange(None)
        if isinstance(ans, int):
            return Exchange(make_response(cmd, ans, b""), elapsed=0.001)
        return Exchange(make_response(cmd, 0, ans), elapsed=0.001)


def make_response(cmd: int, status: int, data: bytes) -> bytes:
    p = bytearray(PACKET_SIZE)
    p[1] = cmd & 0x3F
    p[2] = status
    p[3] = len(data)
    p[4:4 + len(data)] = data
    if status in (0, 1, 2):                      # error responses keep a stale checksum
        p[63] = checksum(p[:63])
    return bytes(p)


class ReadOnlyLink:
    """The only way the scan and repeat modes talk to the keyboard."""

    def __init__(self, device):
        self._dev = device

    def request(self, cmd: int, timeout: float) -> Exchange:
        packet = build_read_request(cmd)
        check_read_only_packet(packet)
        return self._dev.exchange(packet, timeout)


# ---------------------------------------------------------------- scan
def run_scan(link: ReadOnlyLink, ids: list[int], timeout: float = 0.5, pause: float = 0.05,
             sleep=time.sleep, log=print, max_timeouts: int = 3) -> dict:
    """Send one empty read request per id (plus control reads before and after).

    Stops early after ``max_timeouts`` unanswered requests in a row, or if the
    device disappears: on real hardware (fw 2025) ~24 unanswered requests made
    the keyboard drop off the bus until it was replugged.
    """
    for c in ids:
        if not is_read_cmd(c):
            raise UnsafeCommand(f"0x{c:02X} is not a read command")
    results = []
    stray_all: list[str] = []

    def one(cmd: int, role: str) -> dict:
        try:
            ex = link.request(cmd, timeout)
        except OSError as e:
            entry = {"cmd": cmd, "cmd_hex": f"0x{cmd:02X}", "role": role, "outcome": "device_lost",
                     "error": str(e), "elapsed_ms": 0.0}
            results.append(entry)
            log(f"0x{cmd:02X}  device lost ({e}) - stopping. Unplug and replug the keyboard.")
            return entry
        info = analyse_response(ex.response) if ex.response is not None else None
        outcome = classify(info)
        entry = {"cmd": cmd, "cmd_hex": f"0x{cmd:02X}", "role": role, "outcome": outcome,
                 "elapsed_ms": round(ex.elapsed * 1000, 1)}
        if info:
            entry.update({k: info[k] for k in ("status", "status_name", "length", "checksum_ok", "data", "raw")
                          if k in info})
        if ex.stray:
            entry["stray"] = [s.hex(" ") for s in ex.stray]
            stray_all.extend(entry["stray"])
        results.append(entry)
        log(format_scan_line(entry))
        return entry

    aborted = None
    control_before = one(CONTROL_CMD, "control-before")
    alive = control_before["outcome"] == "data"
    if not alive:
        log("control read 0x05 got no data - not scanning further (is the right device open?)")
    else:
        in_a_row = 0
        for cmd in ids:
            sleep(pause)
            outcome = one(cmd, "probe")["outcome"]
            if outcome == "device_lost":
                aborted = "device_lost"
                break
            in_a_row = in_a_row + 1 if outcome == "timeout" else 0
            if in_a_row >= max_timeouts:
                aborted = f"{max_timeouts} unanswered requests in a row"
                log(f"stopping early: {aborted} (the firmware ignores unknown ids; "
                    "too many of them made the keyboard drop off the bus)")
                break
        if aborted != "device_lost":
            sleep(pause)
            control_after = one(CONTROL_CMD, "control-after")
            if control_after["outcome"] != "data":
                log("WARNING: the keyboard no longer answers the control read. Unplug and replug it.")
    probes = [r for r in results if r["role"] == "probe"]
    summary = {
        "sent": len(results),
        "interesting": [r["cmd_hex"] for r in probes if r["outcome"] == "data"],
        # answered with anything but "not supported": the id may exist and only want parameters
        "recognised": [r["cmd_hex"] for r in probes
                       if r["outcome"] not in ("timeout", "odd", "status:NOT_SUPPORTED")],
        "empty_answers": [r["cmd_hex"] for r in probes if r["outcome"] == "empty"],
        "error_status": {r["cmd_hex"]: r["status_name"] for r in probes if r["outcome"].startswith("status:")},
        "timeouts": [r["cmd_hex"] for r in probes if r["outcome"] == "timeout"],
        "stopped_early": aborted,
        "control_ok_after": bool(results) and results[-1]["role"] == "control-after"
        and results[-1]["outcome"] == "data",
    }
    return {"results": results, "summary": summary, "stray": stray_all}


def format_scan_line(entry: dict) -> str:
    head = f"{entry['cmd_hex']}  {entry['outcome']:<22s}"
    if entry["outcome"] in ("data", "empty", "bad-checksum") or entry["outcome"].startswith("status:"):
        data = entry.get("data", "")
        if len(data) > 47:
            data = data[:47] + " ..."
        head += f" status={entry.get('status')} len={entry.get('length')}"
        if data:
            head += f"  {data}"
    mark = "  <-- DATA" if entry["outcome"] == "data" and entry["role"] == "probe" else ""
    return head + f"  ({entry['elapsed_ms']} ms){mark}"


# ---------------------------------------------------------------- repeat
def shown_length(*blobs: bytes | None, minimum: int = 8) -> int:
    """Length to display: up to the last non-zero byte of any blob (trailing zeros are noise)."""
    n = 0
    for blob in blobs:
        if blob:
            n = max(n, len(blob.rstrip(b"\x00")))
    return max(n, minimum)


def highlight_changes(prev: bytes | None, cur: bytes, color: bool = False) -> str:
    """Hex dump of `cur`; bytes differing from `prev` are marked.

    Marking: ANSI bold red if `color`, otherwise ``[xx]``. Trailing zero bytes that are
    zero in both samples are left out.
    """
    parts = []
    for i, b in enumerate(cur[:shown_length(prev, cur)]):
        changed = prev is not None and i < len(prev) and prev[i] != b
        h = f"{b:02x}"
        if changed:
            h = f"\x1b[1;31m{h}\x1b[0m" if color else f"[{h}]"
        parts.append(h)
    return " ".join(parts)


def run_repeat(link: ReadOnlyLink, cmd: int, seconds: float = 15.0, interval: float = 0.1,
               timeout: float = 0.5, color: bool = False, log=print,
               clock=time.monotonic, sleep=time.sleep) -> dict:
    """Poll one read command and report which bytes of the answer ever change."""
    if not is_read_cmd(cmd):
        raise UnsafeCommand(f"0x{cmd:02X} is not a read command")
    interval = max(interval, 0.02)           # at most 50 requests per second
    # compare bytes 2..62: status, length and payload (not the checksum)
    lo, hi = 2, 63
    t0 = clock()
    base: bytes | None = None
    prev: bytes | None = None
    samples = timeouts = 0
    changed_offsets: set[int] = set()
    seen: dict[int, set[int]] = {}
    events = []
    last_beat = t0
    while clock() - t0 < seconds:
        ex = link.request(cmd, timeout)
        now = clock() - t0
        if ex.response is None or len(ex.response) != PACKET_SIZE:
            timeouts += 1
            if timeouts >= 5 and samples == 0:
                log("no answer to 5 requests - stopping")
                break
        else:
            cur = ex.response[lo:hi]
            samples += 1
            if base is None:
                base = cur
                log(f"t={now:6.2f}s  baseline  {cur[:shown_length(cur)].hex(' ')}")
            if prev is not None and cur != prev:
                diff = [lo + i for i in range(len(cur)) if cur[i] != prev[i]]
                changed_offsets.update(diff)
                if len(events) < 500:
                    events.append({"t": round(now, 3), "offsets": diff, "data": cur.hex(" ")})
                log(f"t={now:6.2f}s  changed   {highlight_changes(prev, cur, color)}   @{diff}")
                last_beat = clock()
            elif clock() - last_beat >= 2.0:
                log(f"t={now:6.2f}s  unchanged ({samples} samples)")
                last_beat = clock()
            for i in range(len(cur)):
                seen.setdefault(lo + i, set()).add(cur[i])
            prev = cur
        sleep(interval)
    ranges = {str(o): {"min": min(seen[o]), "max": max(seen[o]), "distinct": len(seen[o])}
              for o in sorted(changed_offsets)}
    return {
        "cmd": cmd, "cmd_hex": f"0x{cmd:02X}", "interval_s": interval, "seconds": seconds,
        "samples": samples, "timeouts": timeouts,
        "baseline": base.hex(" ") if base else None,
        "changed_offsets": sorted(changed_offsets),
        "value_ranges": ranges,
        "events": events,
        "verdict": ("answer changed while polling" if changed_offsets else
                    "answer never changed" if samples else "no answers"),
    }


# ---------------------------------------------------------------- watch
@dataclass
class HidNode:
    path: str
    product_id: int
    descriptor: bytes
    interface: str = ""

    @property
    def is_vendor(self) -> bool:
        return self.descriptor.startswith(b"\x06\x01\xff")


def find_nodes(sysfs: str = "/sys/class/hidraw") -> list[HidNode]:
    """All hidraw nodes of the supported keyboards (every interface, not only the vendor one)."""
    import glob

    from .device import BOOTLOADER, EXPERIMENTAL, SUPPORTED, VENDOR_ID, BootloaderMode, _hid_id
    nodes = []
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
                descriptor = f.read()
        except OSError:
            continue
        node = desc.split(os.sep)[-3]
        iface = ""
        try:  # e.g. ".../3367:5035.0003/..." -> input name for orientation
            with open(os.path.join(devdir, "uevent")) as f:
                for line in f.read().splitlines():
                    if line.startswith("HID_PHYS="):
                        iface = line.split("=", 1)[1]
        except OSError:
            pass
        nodes.append(HidNode(f"/dev/{node}", ids[1], descriptor, iface))
    return nodes


def summarise_descriptor(desc: bytes) -> dict:
    """Minimal HID report descriptor parser: usage pages, report ids, input report sizes."""
    pages: list[int] = []
    ids: list[int] = []
    bits: dict[int, int] = {}
    size = count = rid = 0
    i = 0
    while i < len(desc):
        prefix = desc[i]
        if prefix == 0xFE:                      # long item, skip
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        n = (0, 1, 2, 4)[prefix & 3]
        val = int.from_bytes(desc[i + 1:i + 1 + n], "little")
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:                           # global
            if tag == 0 and val not in pages:
                pages.append(val)
            elif tag == 7:
                size = val
            elif tag == 8:
                rid = val
                if val not in ids:
                    ids.append(val)
            elif tag == 9:
                count = val
        elif kind == 0 and tag == 8:            # main: Input
            bits[rid] = bits.get(rid, 0) + size * count
        i += 1 + n
    return {
        "usage_pages": [f"0x{p:04X}" for p in pages],
        "report_ids": ids,
        "input_bytes_per_report_id": {str(k): (v + 7) // 8 for k, v in sorted(bits.items())},
    }


def describe_report(raw: bytes) -> str:
    """Best-effort label for an unsolicited report."""
    if len(raw) >= 4 and raw[0] == 4 and raw[1] in EVENT_NAMES:
        return f"EVENT 0x{raw[1]:02X}: {EVENT_NAMES[raw[1]]}"
    if len(raw) >= 3 and raw[0] in EVENT_NAMES:
        return f"event 0x{raw[0]:02X} without report-id byte? {EVENT_NAMES[raw[0]]}"
    if len(raw) >= 2 and raw[0] == 4:
        return f"report id 4, unknown code 0x{raw[1]:02X}  <-- new, please report"
    if len(raw) == PACKET_SIZE and raw[0] == 0 and raw[63] == checksum(raw[:63]):
        return f"config packet cmd=0x{raw[1] & 0x3F:02X} status={raw[2]}"
    return ""


def run_watch(nodes: list[HidNode], seconds: float, log=print, clock=time.monotonic,
              opener=None) -> dict:
    """Passively read every given hidraw node for `seconds`; nothing is ever written."""
    opener = opener or (lambda p: os.open(p, os.O_RDONLY | os.O_NONBLOCK))
    fds: dict[int, HidNode] = {}
    for n in nodes:
        try:
            fds[opener(n.path)] = n
        except OSError as e:
            log(f"cannot open {n.path}: {e}")
    reports = []
    counts: dict[str, dict[str, int]] = {}
    t0 = clock()
    try:
        while fds and clock() - t0 < seconds:
            ready, _, _ = select.select(list(fds), [], [], min(0.25, max(0.0, seconds - (clock() - t0))))
            for fd in ready:
                node = fds[fd]
                try:
                    raw = os.read(fd, 256)
                except BlockingIOError:
                    continue
                except OSError as e:
                    if e.errno == errno.ENODEV:
                        log(f"{node.path}: device disappeared")
                        del fds[fd]
                        break
                    raise
                label = describe_report(raw)
                key = raw[:8].hex(" ")
                per = counts.setdefault(node.path, {})
                per[key] = per.get(key, 0) + 1
                entry = {"t": round(clock() - t0, 3), "node": node.path, "size": len(raw),
                         "hex": raw.hex(" "), "label": label}
                if len(reports) < 2000:
                    reports.append(entry)
                log(f"t={entry['t']:7.3f}s {node.path} [{len(raw)}] {raw[:24].hex(' ')}"
                    + (" ..." if len(raw) > 24 else "") + (f"   {label}" if label else ""))
    finally:
        for fd in fds:
            os.close(fd)
    return {
        "seconds": seconds,
        "nodes_watched": [n.path for n in nodes],
        "report_count": sum(sum(v.values()) for v in counts.values()),
        "distinct_first_8_bytes": {p: dict(sorted(v.items(), key=lambda kv: -kv[1])[:50])
                                   for p, v in counts.items()},
        "reports": reports,
        "events_seen": sorted({r["label"] for r in reports if r["label"].startswith(("EVENT", "report id 4"))}),
    }


# ---------------------------------------------------------------- report
def new_report(mode: str, nodes: list[HidNode] | None = None) -> dict:
    from . import __version__
    return {
        "tool": "kb65he probe",
        "version": __version__,
        "mode": mode,
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": {"kernel": platform.release(), "python": platform.python_version()},
        "nodes": [{"path": n.path, "product_id": f"0x{n.product_id:04X}", "phys": n.interface,
                   "vendor_interface": n.is_vendor,
                   "report_descriptor": n.descriptor.hex(" "),
                   "descriptor_summary": summarise_descriptor(n.descriptor)} for n in (nodes or [])],
    }


def write_report(report: dict, path: str) -> str:
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return path


def default_report_name(mode: str) -> str:
    return f"kb65he-probe-{mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
