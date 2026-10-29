#!/usr/bin/env python3
"""Does a lighting write count as a stored change (flash write)?

Background: for a game integration (e.g. CS2 health on the keyboard) the lighting
would have to be rewritten while playing. If every write increments the change
counter (command 0x05, "increments on every stored change"), that is probably a
flash write and must not be done at high rate.

The test, with the keyboard connected:
  1. write the unchanged lighting once            -> does an identical write count?
  2. write N different colours into slot 0        -> does each write count? how long does it take?
  3. restore the original lighting (always, also on Ctrl+C / errors)

Run:  python3 scripts/lighting_write_test.py [--count 10] [--delay 0.3]
(from the repo: PYTHONPATH=src python3 scripts/lighting_write_test.py)
Watch the keyboard: it should switch to static and cycle red/green/blue.
"""
from __future__ import annotations

import argparse
import copy
import sys
import time

from kb65he.device import KB65HE, DeviceNotFound, FakeTransport

PALETTE = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]


def counter(kb: KB65HE) -> int:
    time.sleep(0.05)
    return kb.revision()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=10, help="number of colour writes (default 10, max 50)")
    ap.add_argument("--delay", type=float, default=0.3, help="pause between writes in seconds (default 0.3)")
    ap.add_argument("--demo", action="store_true", help="use the in-memory fake keyboard")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if not 1 <= args.count <= 50:
        ap.error("--count must be 1..50 (every write may wear the flash)")

    try:
        kb = KB65HE(FakeTransport()) if args.demo else KB65HE.open(verbose=args.verbose)
    except DeviceNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    original = kb.read_lighting()
    print(f"original lighting: on={original.on} effect={original.effect} "
          f"brightness={original.brightness} speed={original.speed} slot={original.color_index}")
    print(f"serial: {kb.serial()}")
    c_start = counter(kb)
    print(f"change counter at start: {c_start}\n")

    try:
        # 1. identical write
        kb.write_lighting(copy.deepcopy(original))
        c1 = counter(kb)
        print(f"1) identical write:   counter {c_start} -> {c1}  (+{c1 - c_start})")

        # 2. N different colours in slot 0, static effect
        test = copy.deepcopy(original)
        test.on, test.effect, test.brightness, test.color_index = True, 1, 9, 0
        times, mismatches = [], 0
        for i in range(args.count):
            test.colors[0] = PALETTE[i % len(PALETTE)]
            t0 = time.monotonic()
            kb.write_lighting(test)
            times.append(time.monotonic() - t0)
            if kb.read_lighting().colors[0] != test.colors[0]:
                mismatches += 1
            time.sleep(args.delay)
        c2 = counter(kb)
        print(f"2) {args.count} colour writes: counter {c1} -> {c2}  (+{c2 - c1})")
        print(f"   write time: avg {1000 * sum(times) / len(times):.0f} ms, max {1000 * max(times):.0f} ms")
        print(f"   read-back mismatches: {mismatches}")
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        # 3. restore
        kb.write_lighting(original)
        ok = kb.read_lighting().to_bytes() == original.to_bytes()
        c3 = counter(kb)
        print(f"3) restored original: {'OK' if ok else 'MISMATCH - check lighting in the GUI'}, counter now {c3}")
        kb.close()

    print("\nInterpretation:")
    print("  counter +N for N writes -> every write is a stored change (flash); use sparingly.")
    print("  counter +0 / small      -> live writes look cheap; a game integration is feasible.")
    print("  Please also note: did the keyboard colour change visibly with each write?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
