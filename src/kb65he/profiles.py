"""Profiles: save the keyboard settings to JSON files and apply them again.

A profile contains the trigger table (actuation point + rapid trigger per key)
and the lighting. The raw key map is stored as well (``keymap_raw``). Restoring it
is EXPERIMENTAL: it is only written if ``"keymap"`` is requested explicitly in
``parts`` together with ``experimental=True``, and an automatic backup is saved
first. Plain ``apply(kb, profile)`` never touches the key map.

Profiles live in ``$XDG_CONFIG_HOME/kb65he/profiles`` (default
``~/.config/kb65he/profiles``); ``export``/``import`` work with any path.
Automatic key map backups go to ``~/.config/kb65he/backups/keymap-<timestamp>.json``.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .keymap import ExperimentalDisabled, Keymap, KeymapError
from .device import (
    ACTUATION_MAX,
    ACTUATION_MIN,
    BRIGHTNESS_MAX,
    KB65HE,
    LIGHT_EFFECTS,
    NUM_KEYS,
    SPEED_MAX,
    Lighting,
)

FORMAT = "kb65he-profile"
VERSION = 1
PARTS = ("trigger", "lighting")           # applied by default
PART_KEYMAP = "keymap"                    # experimental, never applied by default
ALL_PARTS = PARTS + (PART_KEYMAP,)


class ProfileError(ValueError):
    pass


def profile_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "kb65he" / "profiles"


def backup_dir() -> Path:
    return profile_dir().parent / "backups"


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    if not slug:
        raise ProfileError("profile name must contain letters or digits")
    return slug[:64]


def path_for(name: str) -> Path:
    return profile_dir() / f"{_slug(name)}.json"


# --- capture / apply ---------------------------------------------------------
def capture(kb: KB65HE, name: str) -> dict:
    """Read the current settings from the keyboard into a profile dict."""
    trig = kb.read_trigger()
    li = kb.read_lighting()
    keys = []
    for k in range(NUM_KEYS):
        a, b = trig.get(k, (None, None))
        keys.append({
            "key": k,
            "actuation": None if a is None else a / 10,
            "rapid_trigger": None if b is None else b / 10,
        })
    try:
        keymap = kb.read_keymap().to_bytes().hex()  # completed to 276 bytes
    except Exception:  # noqa: BLE001 - optional
        keymap = None
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device": {"product_id": f"{kb.info.product_id:04x}" if kb.info else None},
        "trigger": keys,
        "lighting": {
            "on": li.on,
            "effect": LIGHT_EFFECTS[li.effect] if li.effect < len(LIGHT_EFFECTS) else li.effect,
            "brightness": li.brightness,
            "speed": li.speed,
            "color_slot": li.color_index,
            "colors": ["#%02x%02x%02x" % c for c in li.colors],
        },
        "keymap_raw": keymap,
    }


def validate(profile: dict) -> dict:
    """Check a profile dict and return it normalised. Raises ProfileError."""
    if not isinstance(profile, dict) or profile.get("format") != FORMAT:
        raise ProfileError("not a kb65he profile")
    if profile.get("version") != VERSION:
        raise ProfileError(f"unsupported profile version {profile.get('version')}")

    trig = profile.get("trigger")
    if trig is not None:
        if not isinstance(trig, list):
            raise ProfileError("'trigger' must be a list")
        for e in trig:
            k = e.get("key") if isinstance(e, dict) else None
            if not isinstance(k, int) or not 0 <= k < NUM_KEYS:
                raise ProfileError(f"invalid key entry: {e!r}")
            for field in ("actuation", "rapid_trigger"):
                v = e.get(field)
                if v is not None and (not isinstance(v, (int, float))
                                      or not ACTUATION_MIN <= round(v * 10) <= ACTUATION_MAX):
                    raise ProfileError(f"key {k}: {field} {v!r} out of range 0.1..4.0")

    raw = profile.get("keymap_raw")
    if raw is not None:
        try:
            bytes.fromhex(raw)
        except (TypeError, ValueError) as e:
            raise ProfileError("'keymap_raw' must be a hex string") from e

    li = profile.get("lighting")
    if li is not None:
        if not isinstance(li, dict):
            raise ProfileError("'lighting' must be an object")
        eff = li.get("effect")
        if isinstance(eff, str):
            if eff not in LIGHT_EFFECTS:
                raise ProfileError(f"unknown effect {eff!r}")
        elif not isinstance(eff, int) or not 0 <= eff < len(LIGHT_EFFECTS):
            raise ProfileError(f"invalid effect {eff!r}")
        for field, hi in (("brightness", BRIGHTNESS_MAX), ("speed", SPEED_MAX), ("color_slot", 6)):
            v = li.get(field)
            if not isinstance(v, int) or not 0 <= v <= hi:
                raise ProfileError(f"lighting {field} {v!r} out of range 0..{hi}")
        colors = li.get("colors")
        if not isinstance(colors, list) or len(colors) != 7 or not all(
                isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors):
            raise ProfileError("lighting colors must be 7 entries like '#ff8800'")
    return profile


def apply(kb: KB65HE, profile: dict, parts=PARTS, *, experimental: bool = False,
          backups: list | None = None) -> list[str]:
    """Write a profile to the keyboard. Returns the list of applied parts.

    ``"keymap"`` in ``parts`` (EXPERIMENTAL) needs ``experimental=True``; a backup of
    the current key map is saved first and its path appended to ``backups``.
    Everything is checked before the first write.
    """
    validate(profile)
    keymap = None
    if PART_KEYMAP in parts:
        if not experimental:
            raise ExperimentalDisabled(
                "restoring the key map is experimental and has not been verified on hardware")
        raw = profile.get("keymap_raw")
        if not raw:
            raise ProfileError("this profile contains no key map")
        try:
            keymap = Keymap.from_hex(raw)
        except KeymapError as e:
            raise ProfileError(f"profile key map is invalid: {e}") from e
    done = []
    if "trigger" in parts and profile.get("trigger"):
        values = {}
        for e in profile["trigger"]:
            a, rt = e.get("actuation"), e.get("rapid_trigger")
            if a is not None or rt is not None:
                values[e["key"]] = (a, rt)
        if values:
            kb.write_trigger(values)
            done.append("trigger")
    if "lighting" in parts and profile.get("lighting"):
        li = profile["lighting"]
        eff = li["effect"]
        kb.write_lighting(Lighting(
            on=bool(li.get("on", True)),
            effect=LIGHT_EFFECTS.index(eff) if isinstance(eff, str) else eff,
            brightness=li["brightness"],
            speed=li["speed"],
            color_index=li["color_slot"],
            colors=[tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in li["colors"]],  # type: ignore[misc]
        ))
        done.append("lighting")
    if keymap is not None:
        write_keymap_safely(kb, keymap, experimental=True, backups=backups)
        done.append(PART_KEYMAP)
    return done


# --- key map safety ------------------------------------------------------------
def backup_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = backup_dir()
    p = d / f"keymap-{stamp}.json"
    n = 1
    while p.exists():
        p = d / f"keymap-{stamp}-{n}.json"
        n += 1
    return p


def backup_keymap(kb: KB65HE, current: Keymap | None = None) -> Path:
    """Save a full profile (incl. the raw key map) to the backup directory.

    Raises ProfileError if the key map could not be captured; callers must not write
    in that case.
    """
    current = current if current is not None else kb.read_keymap()
    path = backup_path()
    prof = capture(kb, path.stem)
    if prof.get("keymap_raw") != current.to_bytes().hex():
        raise ProfileError("could not back up the key map - nothing was written")
    return write_file(prof, path)


def write_keymap_safely(kb: KB65HE, keymap: Keymap, *, experimental: bool = False,
                        backups: list | None = None) -> Keymap:
    """Write a key map after saving an automatic backup (EXPERIMENTAL).

    Order: experimental flag -> validation -> backup -> write -> read-back compare.
    If any step before the write fails, the keyboard is not touched. The backup path
    is appended to ``backups`` if given.
    """
    def before(current: Keymap) -> None:
        path = backup_keymap(kb, current)
        if backups is not None:
            backups.append(path)

    return kb.write_keymap(keymap, experimental=experimental, before_write=before)


# --- files -------------------------------------------------------------------
def read_file(path: str | os.PathLike) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ProfileError(f"invalid JSON in {path}: {e}") from e
    return validate(data)


def write_file(profile: dict, path: str | os.PathLike) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)
    return p


def save(profile: dict) -> Path:
    return write_file(profile, path_for(profile["name"]))


def load(name: str) -> dict:
    p = path_for(name)
    if not p.exists():
        raise ProfileError(f"no profile named {name!r}")
    return read_file(p)


def delete(name: str) -> None:
    p = path_for(name)
    if not p.exists():
        raise ProfileError(f"no profile named {name!r}")
    p.unlink()


def list_profiles() -> list[dict]:
    """Return valid profiles sorted by name (broken files are skipped)."""
    out = []
    d = profile_dir()
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            prof = read_file(p)
        except (ProfileError, OSError):
            continue
        prof["_path"] = str(p)
        out.append(prof)
    return sorted(out, key=lambda x: str(x.get("name", "")).lower())


def summary(profile: dict, t=lambda s: s) -> str:
    """Short human-readable description, e.g. '1.0 mm · RT 0.2 mm · surf_left'.

    `t` translates the words "RT off", "light off" and effect names.
    """
    acts = [e["actuation"] for e in profile.get("trigger") or [] if e.get("actuation") is not None]
    rts = [e["rapid_trigger"] for e in profile.get("trigger") or [] if e.get("rapid_trigger") is not None]
    parts = []
    if acts:
        lo, hi = min(acts), max(acts)
        parts.append(f"{lo:.1f} mm" if lo == hi else f"{lo:.1f}–{hi:.1f} mm")
    if rts:
        on = [r for r in rts if r < 4.0]
        if not on:
            parts.append(t("RT off"))
        else:
            lo, hi = min(on), max(on)
            parts.append(f"RT {lo:.1f} mm" if lo == hi else f"RT {lo:.1f}–{hi:.1f} mm")
    li = profile.get("lighting")
    if li:
        parts.append(t(str(li.get("effect"))) if li.get("on", True) else t("light off"))
    return " · ".join(parts)
