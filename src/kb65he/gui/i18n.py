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
    "Rapid Trigger": "Rapid Trigger",
    "Off": "Aus",
    "Show": "Anzeige",
    "less sensitive": "weniger empfindlich",
    "{n} keys saved": "{n} Tasten gespeichert",
    "Rapid Trigger: the key re-triggers as soon as it moves this far down or up, instead of waiting for the fixed actuation point.":
        "Rapid Trigger: Die Taste löst erneut aus, sobald sie sich um diese Strecke nach unten oder oben bewegt, statt auf den festen Auslösepunkt zu warten.",
    "Profiles": "Profile",
    "Save the current keyboard settings and load them again later.":
        "Speichere die aktuellen Einstellungen der Tastatur und lade sie später wieder.",
    "Name, e.g. Gaming": "Name, z. B. Gaming",
    "Save current settings": "Aktuelle Einstellungen speichern",
    "Import…": "Importieren…",
    "Export…": "Exportieren…",
    "Load": "Laden",
    "Delete": "Löschen",
    "No profiles yet.": "Noch keine Profile.",
    "Profiles contain actuation points, rapid trigger and lighting. Stored in {path}":
        "Profile enthalten Auslösepunkte, Rapid Trigger und Beleuchtung. Gespeichert in {path}",
    "Enter a name first": "Bitte zuerst einen Namen eingeben",
    "Overwrite profile \u201c{name}\u201d?": "Profil \u201e{name}\u201c überschreiben?",
    "Delete profile \u201c{name}\u201d?": "Profil \u201e{name}\u201c löschen?",
    "Profile \u201c{name}\u201d saved": "Profil \u201e{name}\u201c gespeichert",
    "Profile \u201c{name}\u201d loaded": "Profil \u201e{name}\u201c geladen",
    "Profile \u201c{name}\u201d imported": "Profil \u201e{name}\u201c importiert",
    "Export profile": "Profil exportieren",
    "RT off": "RT aus",
    "light off": "Licht aus",
    "Import profile": "Profil importieren",
    "Exported to {path}": "Exportiert nach {path}",
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
    "Key map": "Tastenbelegung",
    "Key assignment of the normal layer and the Fn layer. Read-only for now.":
        "Tastenbelegung der normalen Ebene und der Fn-Ebene. Vorerst nur Anzeige.",
    "Key": "Taste",
    "Normal": "Normal",
    "Fn layer": "Fn-Ebene",
    "Highlighted entries differ from the factory default.":
        "Hervorgehobene Einträge weichen von der Werkseinstellung ab.",
    "Same as the factory default.": "Entspricht der Werkseinstellung.",
    "{n} entries differ from the factory default.": "{n} Einträge weichen von der Werkseinstellung ab.",
    "Remapping is experimental and only available in the command line for now: kb65he keymap --help":
        "Umbelegen ist experimentell und vorerst nur in der Kommandozeile möglich: kb65he keymap --help",
    "Could not read the key map: {err}": "Tastenbelegung konnte nicht gelesen werden: {err}",
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
