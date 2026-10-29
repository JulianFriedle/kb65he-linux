# Hardware test plan: key remapping (issue #2)

Status: write verified on hardware (2026-10-29, KB65HE 8k ISO): read OK (firmware returns 272 of 276 bytes,
factory default corrected), full rewrite identical, Fn+G → Pause produced `KEY_PAUSE` while G stayed `KEY_G`.
Survives a replug (Fn+G was still Pause afterwards). Still open: `reset-default`. Work through the steps in order and stop at the first surprise.
Background and evidence: [PROTOCOL.md, "Key map"](PROTOCOL.md#key-map).

Every write command saves a backup first
(`~/.config/kb65he/backups/keymap-<timestamp>.json`), reads the table back and compares it. If the read-back
differs, the previous table is written back once and the command fails.

## 0. Preparation

1. Have a **second keyboard** (any USB keyboard, or a laptop keyboard) available. The configurator talks to the
   keyboard over hidraw, so it keeps working even if the KB65HE types garbage, but you want a way to type
   commands.
2. Check out the branch and install it in a throwaway virtualenv:

   ```bash
   cd kb65he-linux
   git fetch origin && git checkout feature/remapping
   python3 -m venv .venv && . .venv/bin/activate
   pip install -e .
   kb65he --version
   ```

3. Close `kb65he-gui` (it polls the keyboard) and any vendor/other HID tools.
4. Make sure the udev rule is installed (`kb65he info` must work without sudo).
5. Optional dry run without hardware: `kb65he --demo keymap set G PAUSE --fn` (uses a simulated
   keyboard and a real backup file) to see what the output looks like.
6. Do **not** unplug the keyboard while a write command is running. Do not use firmware-update functions.

## 1. Read only, and record the starting point (safe)

```bash
kb65he info | tee ~/kb65he-test-info-before.txt
kb65he keymap | tee ~/kb65he-test-keymap-before.txt
kb65he backup ~/kb65he-test-full-backup.json        # explicit extra backup incl. raw key map
python3 - <<'PY'
import json, os
from kb65he.keymap import DEFAULT_HEX
raw = json.load(open(os.path.expanduser("~/kb65he-test-full-backup.json")))["keymap_raw"]
print("identical to built-in default:", raw == DEFAULT_HEX)
print(raw)
PY
```

Expected: the table lists 69 keys with the normal layer and Fn layer (ESC, 1, 2 … / `, F1, F2 …) and ends with
`identical to the factory default`. If the line says `N entries differ`, entries marked `*` are either your
own earlier vendor-software changes or places where the built-in default is wrong. **Post the full output to the
issue before continuing**; the `reset-default` options in steps 4 and 6 are only meaningful if it is identical.

Keep `~/kb65he-test-full-backup.json` — it is the restore point for the whole test.

## 2. Write the unchanged table back (safest write)

This sends the same 276 bytes that were just read. It tests the write command, the status reply and the
read-back without changing any assignment.

```bash
kb65he info | grep Revision                      # note the change counter
kb65he -v keymap rewrite 2>&1 | tee ~/kb65he-test-rewrite.log
kb65he info | grep Revision                      # expect: increased (if the firmware counts it)
kb65he keymap > ~/kb65he-test-keymap-after-rewrite.txt
diff ~/kb65he-test-keymap-before.txt ~/kb65he-test-keymap-after-rewrite.txt && echo SAME
```

Expected: `written and verified by read-back`, `diff` prints nothing, typing still works normally.

Stop and report (attach `~/kb65he-test-rewrite.log`) if: the command fails with a device status
(`BAD_DATA`, `NOT_SUPPORTED` …), times out, reports a read-back mismatch, or keys behave differently.

Persistence check: unplug and replug the keyboard, then `kb65he keymap | diff ~/kb65he-test-keymap-before.txt -`.

## 3. Change one harmless key on the Fn layer

Fn + G normally types `g`; the test makes it send Pause, which does nothing in most programs. The key
`G` is **not** the Fn key and the normal layer is not touched.

```bash
kb65he keymap set G PAUSE --fn        # key 34, Fn layer
kb65he keymap | grep -E '^34 '                        # expect: G ... G  PAUSE*
```

Check it on the machine (pick one):

```bash
sudo evtest                    # choose the "KB65HE" keyboard event device, hold Fn and press G
# or: sudo libinput debug-events --show-keycodes
```

Expected: **Fn + G** produces `KEY_PAUSE` (code 119); **G alone** still produces `KEY_G`; all other Fn
combinations (Fn+1 = F1, Fn+W = lighting colour …) are unchanged.

Then the same for the normal layer, using a key that the second keyboard can replace and that is easy to spot:

```bash
kb65he keymap set 14 INS              # key 14 = Del; now types Insert
```

Expected: pressing Del sends `KEY_INSERT`. (Name `14` is the key number; run `kb65he actuation` for numbers.)

Stop and report if: a different key changes, Fn stops working, the keyboard stops sending anything, or
the command reports a mismatch.

## 4. Revert

```bash
kb65he keymap set G G --fn
kb65he keymap set 14 DEL
kb65he keymap | diff ~/kb65he-test-keymap-before.txt - && echo BACK_TO_START
```

If step 1 said `identical to built-in default` you can instead run
`kb65he keymap reset-default` (writes the whole factory table) and compare again.
Alternatively restore from the explicit backup:

```bash
kb65he restore ~/kb65he-test-full-backup.json --only keymap
```

Then unplug/replug once more and check `kb65he keymap` against the starting point.

## 5. Optional extra checks (only after 1 to 4 passed)

* A media target on the Fn layer: `kb65he keymap set G MUTE --fn`, test, revert (step 4).
* A lighting target: `kb65he keymap set G LIGHTCOLOR --fn` (Fn+G now cycles colours), revert.
* Mouse buttons (`MOUSE1`) are accepted but completely untested; the keyboard may enumerate no mouse interface,
  in which case nothing happens.
* The tool refuses (by design): remapping Fn (key 64, normal layer), overwriting macro/DKS entries,
  unknown codes. `kb65he keymap set 64 A` should print an error and leave the keyboard alone.

## 6. Recovery if something goes wrong

Keep calm: the configurator does not depend on the keyboard's own key assignment.

1. **Restore the automatic backup** (newest first), from any working keyboard or over SSH:

   ```bash
   ls -t ~/.config/kb65he/backups/ | head
   kb65he restore ~/.config/kb65he/backups/keymap-<timestamp>.json --only keymap
   ```

   The newest backup is the state *before the last write*. Or use `~/kb65he-test-full-backup.json` from step 1.
2. **Write the factory default**: `kb65he keymap reset-default`. This is the same table the vendor
   software writes for "restore keys" (it uses the same `0x1A` command; the vendor software has no other reset command).
   It refuses to run if a macro/DKS entry is present; clear it with the vendor software.
3. **Vendor software**: in the Windows software use the key-assignment "Restore" button (internally
   `RestoreFactory(1)`). A Windows machine or VM with USB passthrough is enough.
4. If the command itself fails with `device stayed busy`, a timeout or a status error: unplug, wait 5 seconds,
   replug, run `kb65he info`, then retry step 1 (read only) before anything else.
5. If the keyboard does not show up at all: do not try anything else with this tool. A key-map write cannot put
   the keyboard into bootloader mode (`3367:5033/5034`; the tool refuses to touch it); use the vendor
   instructions. I do not know of an on-keyboard reset shortcut for the key map, so none is documented here.

## 7. What to report back

* Full output of steps 1 and 2 (`kb65he keymap`, the `-v` log of `keymap rewrite`), `Revision` before and after.
* For each of step 3's checks: the `evtest` line you saw.
* Whether the changes survive a replug.
* Any status code, timeout or read-back mismatch message, verbatim.
* The meaning of the unknown firmware codes (`0x16`, `0xF9`, `0xE3`, `0xEF`, `0xF7`) if you can observe what they do.

Steps 1 to 4 passed; since 0.5.0 `--experimental` is no longer needed (still accepted) and the GUI can edit the key map.
