"""Tiny translation table (English default, German if the locale says so)."""
from __future__ import annotations

import locale
import os

_DE = {
    "Actuation": "Auslösung",
    "Lighting": "Beleuchtung",
    "Device": "Gerät",
    "Connected": "Verbunden",
    "Not connected": "Nicht verbunden",
    "Demo mode": "Demo-Modus",
    "Actuation point": "Auslösepunkt",
    "Click keys to select them, then apply a value.": "Tasten anklicken, um sie auszuwählen, dann Wert übernehmen.",
    "All": "Alle",
    "None": "Keine",
    "Invert": "Umkehren",
    "WASD": "WASD",
    "{n} selected": "{n} ausgewählt",
    "Apply to selection": "Auf Auswahl anwenden",
    "Saved to keyboard": "Auf der Tastatur gespeichert",
    "{n} keys set to {mm} mm": "{n} Tasten auf {mm} mm gesetzt",
    "Select at least one key": "Mindestens eine Taste auswählen",
    "more sensitive": "empfindlicher",
    "deeper": "tiefer",
    "Backlight": "Hintergrundbeleuchtung",
    "Effect": "Effekt",
    "Brightness": "Helligkeit",
    "Speed": "Geschwindigkeit",
    "Colour": "Farbe",
    "Click a swatch to make it active, double-click to edit.": "Farbfeld anklicken zum Aktivieren, Doppelklick zum Bearbeiten.",
    "Changes are written to the keyboard immediately.": "Änderungen werden sofort auf die Tastatur geschrieben.",
    "Keyboard not found": "Tastatur nicht gefunden",
    "Plug in the KB65HE 8k. If it is connected, install the udev rule so your user can access it:":
        "KB65HE 8k anschließen. Ist sie angeschlossen, die udev-Regel installieren, damit dein Benutzer Zugriff hat:",
    "Permission denied on {path}": "Kein Zugriff auf {path}",
    "Serial": "Seriennummer",
    "Revision": "Änderungszähler",
    "Interface": "Schnittstelle",
    "Model": "Modell",
    "Legends": "Beschriftung",
    "Unofficial tool, not affiliated with Endgame Gear. Use at your own risk.":
        "Inoffizielles Tool, nicht mit Endgame Gear verbunden. Nutzung auf eigene Gefahr.",
    "Error": "Fehler",
    "spectral_cycle": "Farbwechsel",
    "static": "Statisch",
    "surf_left": "Welle",
    "breathing": "Atmen",
    "snake": "Schlange",
    "magnetic": "Magnetisch",
    "surf_mid": "Welle Mitte",
    "laser": "Laser",
    "cross_surf": "Kreuzwelle",
    "traffic": "Verkehr",
    "ripple": "Wellenring",
}

_EN_NAMES = {
    "spectral_cycle": "Spectrum",
    "static": "Static",
    "surf_left": "Wave",
    "breathing": "Breathing",
    "snake": "Snake",
    "magnetic": "Magnetic",
    "surf_mid": "Wave centre",
    "laser": "Laser",
    "cross_surf": "Cross wave",
    "traffic": "Traffic",
    "ripple": "Ripple",
}


def _is_german() -> bool:
    lang = os.environ.get("KB65HE_LANG") or os.environ.get("LANG") or ""
    if not lang:
        try:
            lang = locale.getlocale()[0] or ""
        except ValueError:
            lang = ""
    return lang.lower().startswith("de")


GERMAN = _is_german()


def tr(text: str, **kw) -> str:
    s = _DE.get(text, _EN_NAMES.get(text, text)) if GERMAN else _EN_NAMES.get(text, text)
    return s.format(**kw) if kw else s
