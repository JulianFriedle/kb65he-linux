"""Command line interface: `kb65he <command>`."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .device import (
    BRIGHTNESS_MAX,
    KB65HE,
    DeviceNotFound,
    LIGHT_EFFECTS,
    NUM_KEYS,
    SPEED_MAX,
    FakeTransport,
)
from .keymap import (
    DEFAULT_KEYMAP,
    LAYER_NAMES,
    TARGETS,
    Entry,
    KeymapError,
    KeymapVerifyError,
    function_name,
    parse_target,
)
from .layout import KEY_BY_INDEX, NAME_TO_INDEX

def _key_label(k: int) -> str:
    key = KEY_BY_INDEX[k]
    return f"{key.labels['de'] or 'Space'}/{key.labels['uk'] or 'Space'}"


def _print_keymap(km) -> None:
    changed = 0
    print("nr  key (DE/UK)   base            Fn")
    for k in range(NUM_KEYS):
        cells = []
        for layer in (0, 1):
            e = km.layers[layer][k]
            mark = "" if e == DEFAULT_KEYMAP.layers[layer][k] else "*"
            changed += bool(mark)
            txt = e.name + (f"({e.param})" if e.param else "")
            cells.append(f"{txt}{mark}")
        print(f"{k:2d}  {_key_label(k):12s}  {cells[0]:14s}  {cells[1]}")
    if changed:
        print(f"\n* = differs from the factory default ({changed} entries)")
    else:
        print("\nidentical to the factory default")


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


def _run_keymap(kb: KB65HE, a, target: int | None) -> None:
    from . import profiles
    try:
        if a.kcmd is None:
            _print_keymap(kb.read_keymap())
            return
        backups: list = []
        before = kb.read_keymap()
        if a.kcmd == "set":
            key = _parse_keys([a.key])[0]
            layer = 1 if a.fn else 0
            new = before.with_entry(layer, key, Entry(target, 0))
            what = (f"key {key} ({_key_label(key)}) {LAYER_NAMES[layer]} layer: "
                    f"{before.get(layer, key).name} -> {function_name(target)}")
        elif a.kcmd == "reset-default":
            new = DEFAULT_KEYMAP
            what = f"factory default key map ({len(before.diff(new))} entries change)"
        else:
            new = before
            what = "current key map written back unchanged"
        print(what)
        after = profiles.write_keymap_safely(kb, new, backups=backups)
        for b in backups:
            print(f"backup:   {b}")
        print("written and verified by read-back" if after == new else "written")
        print("undo with: kb65he restore <backup> --only keymap")
    except (KeymapError, KeymapVerifyError, profiles.ProfileError) as e:
        sys.exit(f"error: {e}")
    except (TimeoutError, OSError) as e:
        sys.exit(f"error talking to the keyboard: {e}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="kb65he", description="Configure the Endgame Gear KB65HE 8k on Linux (unofficial).")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-v", "--verbose", action="store_true", help="print raw packets")
    ap.add_argument("--demo", action="store_true", help="use a simulated keyboard")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show device information")
    sub.add_parser("lighting", help="show lighting settings")

    km = sub.add_parser("keymap", help="show or change the key assignment")
    ksub = km.add_subparsers(dest="kcmd")
    ksub.add_parser("targets", help="list the names accepted as remap targets")
    ks = ksub.add_parser("set", help="assign a function to one key (a backup is saved first)")
    ks.add_argument("key", help="key name or number as in `kb65he actuation`")
    ks.add_argument("target", help="e.g. F5, A, ESC, VOLUP, MUTE (see `kb65he keymap targets`)")
    ks.add_argument("--fn", action="store_true", help="change the Fn layer instead of the normal layer")
    ks.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)  # no longer needed, kept for old scripts
    kr = ksub.add_parser("reset-default", help="write the factory default key map")
    kr.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)  # no longer needed, kept for old scripts
    kw = ksub.add_parser("rewrite", help="write the current key map back unchanged (test)")
    kw.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)  # no longer needed, kept for old scripts
    act = sub.add_parser("actuation", help="show or set actuation points")
    act.add_argument("mm", type=float, nargs="?", help="new actuation point 0.1..4.0 mm")
    act.add_argument("keys", nargs="*", help="key names or numbers (e.g. W A S D)")
    act.add_argument("--all", action="store_true", help="apply to all keys")

    rt = sub.add_parser("rapid-trigger", help="set rapid-trigger distance (re-trigger after lifting/pressing this far)")
    rt.add_argument("mm", help="0.1..4.0 or 'off'")
    rt.add_argument("keys", nargs="*", help="key names or numbers")
    rt.add_argument("--all", action="store_true", help="apply to all keys")

    pr = sub.add_parser("profile", help="save, load and manage profiles")
    psub = pr.add_subparsers(dest="pcmd", required=True)
    psub.add_parser("list", help="list saved profiles")
    for name, hlp in (("save", "save current keyboard settings as a profile"),
                      ("load", "apply a saved profile to the keyboard"),
                      ("delete", "delete a saved profile")):
        sp = psub.add_parser(name, help=hlp)
        sp.add_argument("name")
        if name == "load":
            sp.add_argument("--only", choices=["trigger", "lighting", "keymap"], help="apply only one part")
            sp.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)  # no longer needed
    bk = sub.add_parser("backup", help="save current settings to a JSON file")
    bk.add_argument("file")
    rs = sub.add_parser("restore", help="apply settings from a JSON file")
    rs.add_argument("file")
    rs.add_argument("--only", choices=["trigger", "lighting", "keymap"], help="apply only one part")
    rs.add_argument("--experimental", action="store_true", help=argparse.SUPPRESS)  # no longer needed

    raw = sub.add_parser("trigger-raw", help="(research) write raw trigger bytes A B for one key")
    raw.add_argument("key")
    raw.add_argument("a", type=int, help="actuation, 1..40 (0.1 mm)")
    raw.add_argument("b", type=int, help="rapid-trigger distance, 1..40 (0.1 mm)")

    pr = sub.add_parser("light-probe", help="(research) try effect ids beyond the known ones, one by one")
    pr.add_argument("--first", type=int, default=11, help="first effect id to try (default 11)")
    pr.add_argument("--last", type=int, default=30, help="last effect id to try (default 30)")

    li = sub.add_parser("set-lighting", help="change lighting")
    li.add_argument("--on", choices=["on", "off"])
    li.add_argument("--effect", choices=LIGHT_EFFECTS)
    li.add_argument("--brightness", type=int, choices=range(BRIGHTNESS_MAX + 1), metavar=f"0..{BRIGHTNESS_MAX}")
    li.add_argument("--speed", type=int, choices=range(SPEED_MAX + 1), metavar=f"0..{SPEED_MAX}", help="higher = faster")
    li.add_argument("--color", help="R,G,B for the active colour slot")
    li.add_argument("--slot", type=int, choices=range(7), metavar="0..6", help="active colour slot")

    a = ap.parse_args(argv)
    from . import profiles

    if a.cmd == "profile" and a.pcmd in ("list", "delete"):
        try:
            if a.pcmd == "list":
                items = profiles.list_profiles()
                if not items:
                    print(f"no profiles in {profiles.profile_dir()}")
                for p in items:
                    print(f"{p['name']:24s} {profiles.summary(p)}")
            else:
                profiles.delete(a.name)
                print(f"deleted {a.name}")
        except profiles.ProfileError as e:
            sys.exit(str(e))
        return

    keymap_target = None
    if a.cmd == "keymap":
        if a.kcmd == "targets":
            for kind in ("key", "media", "light", "mouse"):
                names = [n for n, k in TARGETS.values() if k == kind]
                print(f"{kind:6s} {' '.join(names)}")
            return
        if a.kcmd == "set":
            try:
                keymap_target = parse_target(a.target)
            except KeymapError as e:
                sys.exit(str(e))

    # validate profile files before touching the device
    prof_in = None
    try:
        if a.cmd == "profile" and a.pcmd == "load":
            prof_in = profiles.load(a.name)
        elif a.cmd == "restore":
            prof_in = profiles.read_file(a.file)
    except (profiles.ProfileError, OSError) as e:
        sys.exit(str(e))

    try:
        kb = KB65HE(FakeTransport()) if a.demo else KB65HE.open(verbose=a.verbose)
    except DeviceNotFound:
        sys.exit("KB65HE 8k not found. Is it plugged in and is the udev rule installed? (see README)")
    except PermissionError as e:
        sys.exit(f"{e}\nInstall the udev rule (see README) and replug the keyboard.")
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
        elif a.cmd == "keymap":
            _run_keymap(kb, a, keymap_target)
        elif a.cmd == "actuation":
            if a.mm is None:
                trig = kb.read_trigger()
                print("nr  DE     UK     actuation  rapid trigger")
                for k in range(NUM_KEYS):
                    key = KEY_BY_INDEX[k]
                    if k in trig:
                        a_, b_ = trig[k]
                        rtxt = "off" if b_ >= 40 else f"{b_ / 10:.1f} mm"
                        val = f"{a_ / 10:.1f} mm     {rtxt}"
                    else:
                        val = "?  (not reported by firmware)"
                    print(f"{k:2d}  {key.labels['de'] or 'Space':6s} {key.labels['uk'] or 'Space':6s} {val}")
            else:
                keys = list(range(NUM_KEYS)) if a.all else _parse_keys(a.keys)
                if not keys:
                    sys.exit("give key names/numbers or --all")
                kb.write_actuation({k: a.mm for k in keys})
                now = kb.read_actuation()
                bad = [k for k in keys if k in now and abs(now[k] - a.mm) > 0.05]
                print(f"{len(keys)} key(s) set to {a.mm:.1f} mm" + (f" - MISMATCH: {bad}" if bad else ""))
        elif a.cmd == "rapid-trigger":
            mm = 4.0 if a.mm.lower() == "off" else float(a.mm)
            keys = list(range(NUM_KEYS)) if a.all else _parse_keys(a.keys)
            if not keys:
                sys.exit("give key names/numbers or --all")
            kb.write_rapid_trigger({k: mm for k in keys})
            print(f"{len(keys)} key(s): rapid trigger " + ("off" if mm >= 4.0 else f"{mm:.1f} mm"))
        elif a.cmd in ("profile", "backup", "restore"):
            try:
                if a.cmd == "backup" or (a.cmd == "profile" and a.pcmd == "save"):
                    name = a.name if a.cmd == "profile" else os.path.splitext(os.path.basename(a.file))[0]
                    prof = profiles.capture(kb, name)
                    path = profiles.save(prof) if a.cmd == "profile" else profiles.write_file(prof, a.file)
                    print(f"saved {path}")
                else:
                    prof = prof_in
                    parts = (a.only,) if a.only else profiles.PARTS
                    backups: list = []
                    done = profiles.apply(kb, prof, parts, backups=backups)
                    for b in backups:
                        print(f"key map backup: {b}")
                    print(f"applied {prof.get('name', '')}: {', '.join(done) or 'nothing'}")
            except (profiles.ProfileError, KeymapError, KeymapVerifyError) as e:
                sys.exit(str(e))
        elif a.cmd == "trigger-raw":
            from .protocol import Cmd
            key = _parse_keys([a.key])[0]
            if not (1 <= a.a <= 40 and 1 <= a.b <= 40):
                sys.exit("values must be 1..40")
            print("before:", kb.read_trigger().get(key, "?"))
            kb.set(Cmd.SET_TRIGGER, bytes([key, 2, a.a, a.b]))
            print("after: ", kb.read_trigger().get(key, "?"))
        elif a.cmd == "light-probe":
            if not (0 <= a.first <= a.last <= 255):
                sys.exit("--first/--last must satisfy 0 <= first <= last <= 255")
            orig = kb.read_lighting()
            print(f"current: effect={orig.effect}; it is restored at the end (or press Ctrl+C).")
            print("Enter = next id, q + Enter = stop. Note every id that shows something new.")
            try:
                for eid in range(a.first, a.last + 1):
                    li_ = kb.read_lighting()
                    li_.effect = eid
                    kb.write_lighting(li_)
                    seen = kb.read_lighting().effect
                    if input(f"effect id {eid} (keyboard reports {seen}) > ").strip().lower() == "q":
                        break
            except (KeyboardInterrupt, EOFError):
                print()
            finally:
                kb.write_lighting(orig)
                print(f"restored effect {orig.effect}")
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
