"""Key map (remapping) data model, names and validation.

EXPERIMENTAL: reading the key map is verified on hardware, writing it is not.
See docs/PROTOCOL.md ("Key map") and docs/TESTPLAN-remapping.md.

The key map is one block of 276 bytes: 2 layers x 69 keys x 2 bytes.
Layer 0 is the normal layer, layer 1 is active while Fn is held. Each key
has an entry ``(function, param)``:

* ``function`` is a Windows virtual-key code for ordinary keys (``0x41`` = A) and a
  vendor "function index" for everything else (media, lighting, mouse buttons,
  macro, DKS, ...). It is the same byte the vendor software calls
  ``cbFunctionIndex``.
* ``param`` is 0 for all simple functions. Macro and DKS entries use it as a slot
  reference (decompiled, not verified), so those entries are never edited here.
"""
from __future__ import annotations

from dataclasses import dataclass

NUM_KEYS = 69
NUM_LAYERS = 2
LAYER_NAMES = ("base", "fn")
ENTRY_SIZE = 2
LAYER_SIZE = NUM_KEYS * ENTRY_SIZE            # 138
KEYMAP_SIZE = NUM_LAYERS * LAYER_SIZE         # 276 = 0x114
UNREPORTED_BYTES = 4                          # firmware read drops Fn-layer keys 67 and 68
UNREPORTED = ((1, 67), (1, 68))

FN_KEY = 64                                   # the Fn key itself (base layer holds VK_FN)
VK_FN = 0xF5

# Function indices that carry extra data on the keyboard (slot in `param`).
FN_MACRO = 152          # 0x98
FN_COMBO = 154          # 0x9A  (VK_ACCELERATOR in the vendor software)
FN_DKS_A = 217          # 0xD9
FN_DKS = 218            # 0xDA
PROTECTED_FUNCTIONS = frozenset({FN_MACRO, FN_COMBO, FN_DKS_A, FN_DKS})


class KeymapError(ValueError):
    """The key map or a requested change is invalid."""


class ExperimentalDisabled(PermissionError):
    """Writing the key map needs ``experimental=True``."""


class KeymapVerifyError(IOError):
    """The keyboard returned something different from what was written."""


# --- names -------------------------------------------------------------------
def _build_targets() -> dict[int, tuple[str, str]]:
    """function index -> (name, kind) for everything we are willing to write."""
    t: dict[int, tuple[str, str]] = {}

    def add(code: int, name: str, kind: str = "key") -> None:
        t[code] = (name, kind)

    for c in range(0x41, 0x5B):
        add(c, chr(c))                                   # A..Z
    for c in range(0x30, 0x3A):
        add(c, chr(c))                                   # 0..9
    for i in range(12):
        add(0x70 + i, f"F{i + 1}")
    for i in range(10):
        add(0x60 + i, f"NUM{i}")
    for code, name in {
        0x1B: "ESC", 0x09: "TAB", 0x14: "CAPS", 0x20: "SPACE", 0x0D: "ENTER", 0x08: "BACKSPACE",
        0x2D: "INS", 0x2E: "DEL", 0x24: "HOME", 0x23: "END", 0x21: "PGUP", 0x22: "PGDN",
        0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
        0x2C: "PRTSC", 0x91: "SCROLL", 0x13: "PAUSE", 0x90: "NUMLOCK",
        0x6A: "NUM*", 0x6B: "NUM+", 0x6D: "NUM-", 0x6E: "NUM.", 0x6F: "NUM/", 0x6C: "NUMENTER",
        0xC0: "`", 0xBD: "-", 0xBB: "=", 0xDB: "[", 0xDD: "]", 0xDC: "\\", 0xBA: ";", 0xDE: "'",
        0xBC: ",", 0xBE: ".", 0xBF: "/", 0xE2: "ISO<",
        0xA0: "LSHIFT", 0xA1: "RSHIFT", 0xA2: "LCTRL", 0xA3: "RCTRL", 0xA4: "LALT", 0xA5: "RALT",
        0x5B: "LWIN", 0x5C: "RWIN", 0x5D: "MENU",
    }.items():
        add(code, name)
    for code, name in {
        173: "MUTE", 174: "VOLDOWN", 175: "VOLUP", 176: "NEXT", 177: "PREV",
        179: "PLAYPAUSE", 181: "MEDIAPLAYER",
    }.items():
        add(code, name, "media")
    for code, name in {
        148: "LIGHTEFFECT", 149: "LIGHTCOLOR", 204: "BRIGHTUP", 205: "BRIGHTDOWN",
        206: "SPEEDUP", 207: "SPEEDDOWN",
    }.items():
        add(code, name, "light")
    for code, name in {1: "MOUSE1", 2: "MOUSE2", 4: "MOUSE3", 5: "MOUSE4", 6: "MOUSE5"}.items():
        add(code, name, "mouse")
    return t


TARGETS: dict[int, tuple[str, str]] = _build_targets()
_NAME_TO_CODE: dict[str, int] = {name.upper(): code for code, (name, _) in TARGETS.items()}
_ALIASES = {
    "ESCAPE": "ESC", "RETURN": "ENTER", "BKSP": "BACKSPACE", "BACK": "BACKSPACE", "DELETE": "DEL",
    "INSERT": "INS", "PAGEUP": "PGUP", "PAGEDOWN": "PGDN", "CAPSLOCK": "CAPS", "PRINT": "PRTSC",
    "SCROLLLOCK": "SCROLL", "APPS": "MENU", "WIN": "LWIN", "SHIFT": "LSHIFT", "CTRL": "LCTRL",
    "ALT": "LALT", "ALTGR": "RALT", "VOLUMEUP": "VOLUP", "VOLUMEDOWN": "VOLDOWN",
    "PLAY": "PLAYPAUSE", "NEXTTRACK": "NEXT", "PREVTRACK": "PREV", "OEM102": "ISO<",
    "GRAVE": "`", "MINUS": "-", "EQUALS": "=", "SEMICOLON": ";", "QUOTE": "'", "COMMA": ",",
    "PERIOD": ".", "SLASH": "/", "BACKSLASH": "\\", "LBRACKET": "[", "RBRACKET": "]",
    "LMB": "MOUSE1", "RMB": "MOUSE2", "MMB": "MOUSE3",
}

# Names of entries we may find on the keyboard but never write.
_READ_ONLY_NAMES = {
    FN_MACRO: "Macro", FN_COMBO: "Combo", FN_DKS_A: "DKS?", FN_DKS: "DKS",
    VK_FN: "Fn", 0x00: "-",
}


def function_name(function: int) -> str:
    """Readable name for a function index (unknown ones as ``0xNN``)."""
    if function in TARGETS:
        return TARGETS[function][0]
    return _READ_ONLY_NAMES.get(function, f"0x{function:02x}")


def parse_target(text: str) -> int:
    """Turn ``"F5"``, ``"volup"``, ``"vk:0x41"`` or ``"0x41"`` into a function index.

    Only targets from :data:`TARGETS` are accepted. Names follow the US key legend
    (the operating system's layout then decides the character, e.g. ``Y`` on a German
    layout types ``Z`` if sent from the key that the layout calls Z).
    """
    raw = text.strip()
    if not raw:
        raise KeymapError("empty target")
    low = raw.lower()
    if low.startswith("vk:"):
        low = low[3:]
    code: int | None = None
    if low.startswith("0x"):
        try:
            code = int(low, 16)
        except ValueError:
            code = None
    else:
        name = raw.upper()
        name = _ALIASES.get(name, name)
        code = _NAME_TO_CODE.get(name.upper())
    if code is None or code not in TARGETS:
        raise KeymapError(f"unknown or unsupported target {text!r} (see `kb65he keymap targets`)")
    return code


# --- data model ----------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    function: int
    param: int = 0

    def __post_init__(self):
        if not (0 <= self.function <= 0xFF and 0 <= self.param <= 0xFF):
            raise KeymapError(f"entry out of range: {self.function}, {self.param}")

    @property
    def name(self) -> str:
        return function_name(self.function)

    @property
    def writable(self) -> bool:
        """True if :func:`parse_target` could produce this entry."""
        return self.function in TARGETS and self.param == 0


@dataclass(frozen=True)
class Keymap:
    """Both layers; ``layers[layer][key]`` is an :class:`Entry`."""

    layers: tuple[tuple[Entry, ...], tuple[Entry, ...]]

    @classmethod
    def from_bytes(cls, data: bytes, tail: bytes | None = None) -> "Keymap":
        """Parse a 276-byte block.

        Firmware quirk: reading the block returns only 272 bytes - the last two Fn-layer
        entries (keys 67 and 68, Fn+Down / Fn+Right) are never reported (the trigger
        table read drops its last record the same way). A 272-byte block is completed
        with ``tail`` (the last 4 bytes known to be written) or the factory default.
        """
        if len(data) == KEYMAP_SIZE - UNREPORTED_BYTES:
            if tail is None:
                tail = bytes.fromhex(DEFAULT_HEX)[-UNREPORTED_BYTES:]
            data = bytes(data) + bytes(tail)
        if len(data) != KEYMAP_SIZE:
            raise KeymapError(f"key map must be {KEYMAP_SIZE} bytes, got {len(data)}")
        layers = tuple(
            tuple(Entry(data[l * LAYER_SIZE + k * 2], data[l * LAYER_SIZE + k * 2 + 1])
                  for k in range(NUM_KEYS))
            for l in range(NUM_LAYERS)
        )
        return cls(layers)  # type: ignore[arg-type]

    @classmethod
    def from_hex(cls, text: str) -> "Keymap":
        try:
            return cls.from_bytes(bytes.fromhex(text))
        except ValueError as e:
            if isinstance(e, KeymapError):
                raise
            raise KeymapError(f"invalid hex key map: {e}") from e

    def to_bytes(self) -> bytes:
        out = bytearray()
        for layer in self.layers:
            for e in layer:
                out += bytes([e.function, e.param])
        return bytes(out)

    def get(self, layer: int, key: int) -> Entry:
        _check_pos(layer, key)
        return self.layers[layer][key]

    def with_entry(self, layer: int, key: int, entry: Entry) -> "Keymap":
        _check_pos(layer, key)
        new = [list(l) for l in self.layers]
        new[layer][key] = entry
        return Keymap(tuple(tuple(l) for l in new))  # type: ignore[arg-type]

    def diff(self, other: "Keymap") -> list[tuple[int, int, Entry, Entry]]:
        """Positions where ``other`` differs: ``(layer, key, self_entry, other_entry)``."""
        return [
            (l, k, self.layers[l][k], other.layers[l][k])
            for l in range(NUM_LAYERS) for k in range(NUM_KEYS)
            if self.layers[l][k] != other.layers[l][k]
        ]


def _check_pos(layer: int, key: int) -> None:
    if not isinstance(layer, int) or not 0 <= layer < NUM_LAYERS:
        raise KeymapError(f"layer {layer!r} out of range (0 = base, 1 = Fn)")
    if not isinstance(key, int) or not 0 <= key < NUM_KEYS:
        raise KeymapError(f"key {key!r} out of range 0..{NUM_KEYS - 1}")


# Factory default of the KB65HE 8k ISO, read from an unmodified keyboard (2026-10-29).
# The vendor software's reset table (DevicePlus.dll, VA 0x1800b6090) differs in 5 special
# entries (# key; Fn layer: Tab, Ae, Space, Fn) - writing it would e.g. turn Fn+Tab (the
# on-keyboard actuation mode, 0xF4) into a plain Tab. Keys 67/68 of the Fn layer are never
# reported by the firmware; DOWN/RIGHT as in the vendor table.
DEFAULT_HEX = (
    "1b003100320033003400350036003700380039003000bd00bb0008002e000900"
    "510057004500520054005900550049004f005000db00dd002100140041005300"
    "44004600470048004a004b004c00ba00de00e3000d002200a000e2005a005800"
    "4300560042004e004d00bc00be00bf00a10026002300a2005b00a4002000a500"
    "f500a300250028002700c0007000710072007300740075007600770078007900"
    "7a007b0008002e00f400cf009500ce00520054006a003700380039006b00ae00"
    "af0021001400cd009400cc00460047006e003400350036006d00de00e300b300"
    "2200a000e2005a00580043005600420030003100320033006f00a10026002300"
    "a2005b00a400f600a500f500a300250028002700"
)
DEFAULT_KEYMAP = Keymap.from_hex(DEFAULT_HEX)


def validate_change(current: Keymap, new: Keymap) -> list[tuple[int, int, Entry, Entry]]:
    """Check that going from ``current`` to ``new`` only touches safe entries.

    Rules (everything else must be byte-identical to ``current``):

    * a changed entry must be a known target (:data:`TARGETS`, ``param`` 0) or the
      factory default of that position (so a reset can restore special codes);
    * entries that currently hold macro/combo/DKS data are never overwritten (their
      slot data on the keyboard would be orphaned);
    * the Fn key (key 64 on the base layer) must stay the Fn key.

    Returns the list of changes. Raises :class:`KeymapError`.
    """
    changes = current.diff(new)
    for layer, key, old, entry in changes:
        where = f"{LAYER_NAMES[layer]} layer, key {key}"
        if old.function in PROTECTED_FUNCTIONS:
            raise KeymapError(
                f"{where} holds a {function_name(old.function)} entry - remove it with the "
                "vendor software first, it is not edited here")
        if layer == 0 and key == FN_KEY:
            raise KeymapError("the Fn key (key 64, base layer) cannot be remapped")
        is_default = entry == DEFAULT_KEYMAP.layers[layer][key]
        if not (entry.writable or is_default):
            raise KeymapError(
                f"{where}: {entry.function:#04x}/{entry.param:#04x} is not a supported target")
    return changes
