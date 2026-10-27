"""Command line interface: `kb65he <command>`."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .device import (
    BRIGHTNESS_MAX,
    KB65HE,
    LIGHT_EFFECTS,
    NUM_KEYS,
    SPEED_MAX,
    FakeTransport,
)
from .layout import KEY_BY_INDEX, NAME_TO_INDEX


def _parse_keys(names: list[str]) -> list[int]:
    keys = []
    for n in names:
        if n.isdigit():
            k = int(n)
        else:
            k = NAME_TO_INDEX.get(n.upper(), -1)
        if not 0 <= k < NUM_KEYS:
            sys.exit(f"unknown key: {n}  (see `kb65he actuation` for names/numbers)")
        keys.append(k)
    return keys


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kb65he", description="Configure the Endgame Gear KB65HE 8k on Linux (unofficial).")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-v", "--verbose", action="store_true", help="print raw packets")
    ap.add_argument("--demo", action="store_true", help="use a simulated keyboard")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show device information")
    sub.add_parser("lighting", help="show lighting settings")
    act = sub.add_parser("actuation", help="show or set actuation points")
    act.add_argument("mm", type=float, nargs="?", help="new actuation point 0.1..4.0 mm")
    act.add_argument("keys", nargs="*", help="key names or numbers (e.g. W A S D)")
    act.add_argument("--all", action="store_true", help="apply to all keys")

    raw = sub.add_parser("trigger-raw", help="(research) write raw trigger bytes A B for one key")
    raw.add_argument("key")
    raw.add_argument("a", type=int, help="actuation, 1..40 (0.1 mm)")
    raw.add_argument("b", type=int, help="unknown second value, 1..40")

    li = sub.add_parser("set-lighting", help="change lighting")
    li.add_argument("--on", choices=["on", "off"])
    li.add_argument("--effect", choices=LIGHT_EFFECTS)
    li.add_argument("--brightness", type=int, choices=range(BRIGHTNESS_MAX + 1), metavar=f"0..{BRIGHTNESS_MAX}")
    li.add_argument("--speed", type=int, choices=range(SPEED_MAX + 1), metavar=f"0..{SPEED_MAX}")
    li.add_argument("--color", help="R,G,B for the active colour slot")
    li.add_argument("--slot", type=int, choices=range(7), metavar="0..6", help="active colour slot")

    a = ap.parse_args(argv)
    kb = KB65HE(FakeTransport()) if a.demo else KB65HE.open(verbose=a.verbose)
    try:
        if a.cmd == "info":
            name = kb.info.name if kb.info else "demo"
            print(f"Device:    {name}")
            if kb.info:
                print(f"hidraw:    {kb.info.path}")
            print(f"Serial:    {kb.serial()}")
            print(f"Revision:  {kb.revision()}")
        elif a.cmd == "lighting":
            li_ = kb.read_lighting()
            eff = LIGHT_EFFECTS[li_.effect] if li_.effect < len(LIGHT_EFFECTS) else li_.effect
            print(f"on={li_.on} effect={eff} brightness={li_.brightness} speed={li_.speed} slot={li_.color_index}")
            for i, c in enumerate(li_.colors):
                print(f"  slot {i}: #{c[0]:02x}{c[1]:02x}{c[2]:02x}" + ("  <- active" if i == li_.color_index else ""))
        elif a.cmd == "actuation":
            if a.mm is None:
                values = kb.read_actuation()
                for k in range(NUM_KEYS):
                    key = KEY_BY_INDEX[k]
                    mm = f"{values[k]:.1f} mm" if k in values else "?  (not reported by firmware)"
                    print(f"{k:2d}  {key.labels['de'] or 'Space':6s} {key.labels['uk'] or 'Space':6s} {mm}")
            else:
                keys = list(range(NUM_KEYS)) if a.all else _parse_keys(a.keys)
                if not keys:
                    sys.exit("give key names/numbers or --all")
                kb.write_actuation({k: a.mm for k in keys})
                now = kb.read_actuation()
                bad = [k for k in keys if k in now and abs(now[k] - a.mm) > 0.05]
                print(f"{len(keys)} key(s) set to {a.mm:.1f} mm" + (f" - MISMATCH: {bad}" if bad else ""))
        elif a.cmd == "trigger-raw":
            from .protocol import Cmd
            key = _parse_keys([a.key])[0]
            if not (1 <= a.a <= 40 and 1 <= a.b <= 40):
                sys.exit("values must be 1..40")
            print("before:", kb.read_trigger().get(key, "?"))
            kb.set(Cmd.SET_TRIGGER, bytes([key, 2, a.a, a.b]))
            print("after: ", kb.read_trigger().get(key, "?"))
        elif a.cmd == "set-lighting":
            li_ = kb.read_lighting()
            if a.on:
                li_.on = a.on == "on"
            if a.effect:
                li_.effect = LIGHT_EFFECTS.index(a.effect)
            if a.brightness is not None:
                li_.brightness = a.brightness
            if a.speed is not None:
                li_.speed = a.speed
            if a.slot is not None:
                li_.color_index = a.slot
            if a.color:
                rgb = tuple(int(x) for x in a.color.split(","))
                li_.colors[li_.color_index] = rgb  # type: ignore[assignment]
            kb.write_lighting(li_)
            print("ok")
    finally:
        kb.close()


if __name__ == "__main__":
    main()
