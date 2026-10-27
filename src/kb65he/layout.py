"""Physical layout of the 69-key ISO KB65HE (index = firmware key number)."""
from __future__ import annotations

from dataclasses import dataclass

ENTER_INDEX = 42


@dataclass(frozen=True)
class Key:
    index: int
    x: float      # in key units (1u)
    y: float
    w: float
    labels: dict  # layout name -> legend


# (index, width, de, uk); index None = spacer / ISO Enter top part
_ROWS = [
    [(0, 1, "Esc", "Esc"), (1, 1, "1", "1"), (2, 1, "2", "2"), (3, 1, "3", "3"), (4, 1, "4", "4"),
     (5, 1, "5", "5"), (6, 1, "6", "6"), (7, 1, "7", "7"), (8, 1, "8", "8"), (9, 1, "9", "9"),
     (10, 1, "0", "0"), (11, 1, "ß", "-"), (12, 1, "´", "="), (13, 2, "⌫", "⌫"), (14, 1, "Entf", "Del")],
    [(15, 1.5, "Tab", "Tab"), (16, 1, "Q", "Q"), (17, 1, "W", "W"), (18, 1, "E", "E"), (19, 1, "R", "R"),
     (20, 1, "T", "T"), (21, 1, "Z", "Y"), (22, 1, "U", "U"), (23, 1, "I", "I"), (24, 1, "O", "O"),
     (25, 1, "P", "P"), (26, 1, "Ü", "["), (27, 1, "+", "]"), (None, 1.5, "", ""), (28, 1, "Bild↑", "PgUp")],
    [(29, 1.75, "Caps", "Caps"), (30, 1, "A", "A"), (31, 1, "S", "S"), (32, 1, "D", "D"), (33, 1, "F", "F"),
     (34, 1, "G", "G"), (35, 1, "H", "H"), (36, 1, "J", "J"), (37, 1, "K", "K"), (38, 1, "L", "L"),
     (39, 1, "Ö", ";"), (40, 1, "Ä", "'"), (41, 1, "#", "#"), (42, 1.25, "Enter", "Enter"),
     (43, 1, "Bild↓", "PgDn")],
    [(44, 1.25, "Shift", "Shift"), (45, 1, "<", "\\"), (46, 1, "Y", "Z"), (47, 1, "X", "X"), (48, 1, "C", "C"),
     (49, 1, "V", "V"), (50, 1, "B", "B"), (51, 1, "N", "N"), (52, 1, "M", "M"), (53, 1, ",", ","),
     (54, 1, ".", "."), (55, 1, "-", "/"), (56, 1.75, "Shift", "Shift"), (57, 1, "↑", "↑"),
     (58, 1, "Ende", "End")],
    [(59, 1.25, "Strg", "Ctrl"), (60, 1.25, "Win", "Win"), (61, 1.25, "Alt", "Alt"), (62, 6.25, "", ""),
     (63, 1, "AltGr", "AltGr"), (64, 1, "Fn", "Fn"), (65, 1, "Strg", "Ctrl"), (66, 1, "←", "←"),
     (67, 1, "↓", "↓"), (68, 1, "→", "→")],
]

LAYOUTS = ("de", "uk")
WIDTH_U = 16.0
HEIGHT_U = 5.0


def build_keys() -> list[Key]:
    keys = []
    for y, row in enumerate(_ROWS):
        x = 0.0
        for index, w, de, uk in row:
            if index is not None:
                keys.append(Key(index, x, float(y), float(w), {"de": de, "uk": uk}))
            x += w
    return keys


KEYS = build_keys()
KEY_BY_INDEX = {k.index: k for k in KEYS}

# ISO Enter: top part spans row 1, x 13.5..15
ENTER_TOP = (13.5, 1.0, 1.5)

# name -> index lookup for the CLI (both layouts, case-insensitive)
NAME_TO_INDEX = {}
for _k in KEYS:
    for _name in _k.labels.values():
        if _name:
            NAME_TO_INDEX.setdefault(_name.upper(), _k.index)
NAME_TO_INDEX.setdefault("SPACE", 62)

# Linux evdev key code (input-event-codes.h) -> key index. The Fn key (64) sends nothing.
EVDEV_TO_INDEX = {
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 11, 13: 12, 14: 13,
    111: 14,
    15: 15, 16: 16, 17: 17, 18: 18, 19: 19, 20: 20, 21: 21, 22: 22, 23: 23, 24: 24, 25: 25,
    26: 26, 27: 27, 104: 28,
    58: 29, 30: 30, 31: 31, 32: 32, 33: 33, 34: 34, 35: 35, 36: 36, 37: 37, 38: 38, 39: 39,
    40: 40, 43: 41, 28: 42, 109: 43,
    42: 44, 86: 45, 44: 46, 45: 47, 46: 48, 47: 49, 48: 50, 49: 51, 50: 52, 51: 53, 52: 54,
    53: 55, 54: 56, 103: 57, 107: 58,
    29: 59, 125: 60, 56: 61, 57: 62, 100: 63, 97: 65, 105: 66, 108: 67, 106: 68,
}
