import copy
import json

import pytest

from kb65he import profiles
from kb65he.cli import main as cli_main
from kb65he.device import KB65HE, FakeTransport
from kb65he.keymap import (
    DEFAULT_KEYMAP,
    KEYMAP_SIZE,
    TARGETS,
    Entry,
    Keymap,
    KeymapError,
    KeymapVerifyError,
    function_name,
    parse_target,
    validate_change,
)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def make():
    t = FakeTransport()
    return KB65HE(t), t


# --- parsing -----------------------------------------------------------------
def test_default_matches_hardware_capture():
    raw = DEFAULT_KEYMAP.to_bytes()
    assert len(raw) == KEYMAP_SIZE == 276
    # verified on a real keyboard: base starts Esc,1,2 ; Fn layer starts `,F1,F2
    assert raw[:6].hex() == "1b0031003200"
    assert raw[138:144].hex() == "c00070007100"
    assert DEFAULT_KEYMAP.get(0, 64).function == 0xF5     # Fn key
    assert DEFAULT_KEYMAP.get(0, 62).name == "SPACE"


def test_roundtrip_bytes_and_hex():
    km = Keymap.from_bytes(DEFAULT_KEYMAP.to_bytes())
    assert km == DEFAULT_KEYMAP
    assert Keymap.from_hex(DEFAULT_KEYMAP.to_bytes().hex()) == DEFAULT_KEYMAP
    assert km.get(1, 3) == Entry(0x72, 0)


@pytest.mark.parametrize("bad", [b"", bytes(275), bytes(277)])
def test_wrong_length_rejected(bad):
    with pytest.raises(KeymapError):
        Keymap.from_bytes(bad)
    with pytest.raises(KeymapError):
        Keymap.from_hex("zz")


def test_names_and_targets():
    assert parse_target("a") == 0x41
    assert parse_target("F5") == 0x74
    assert parse_target("volup") == 175
    assert parse_target("vk:0x41") == 0x41
    assert parse_target("Esc") == 0x1B
    assert function_name(0x41) == "A"
    assert function_name(0xF9) == "0xf9"
    for bad in ("", "nonsense", "0x98", "0xf5", "0x00", "macro"):
        with pytest.raises(KeymapError):
            parse_target(bad)


# --- validation ----------------------------------------------------------------
def test_validate_accepts_plain_remap():
    new = DEFAULT_KEYMAP.with_entry(1, 3, Entry(0x74, 0))
    assert [(c[0], c[1]) for c in validate_change(DEFAULT_KEYMAP, new)] == [(1, 3)]


def test_validate_rejects_unsafe_changes():
    # unknown function, non-zero param, Fn key, protected entries, out of range
    with pytest.raises(KeymapError):
        validate_change(DEFAULT_KEYMAP, DEFAULT_KEYMAP.with_entry(0, 5, Entry(0x16, 0)))
    with pytest.raises(KeymapError):
        validate_change(DEFAULT_KEYMAP, DEFAULT_KEYMAP.with_entry(0, 5, Entry(0x41, 7)))
    with pytest.raises(KeymapError):
        validate_change(DEFAULT_KEYMAP, DEFAULT_KEYMAP.with_entry(0, 64, Entry(0x41, 0)))
    with pytest.raises(KeymapError):
        validate_change(DEFAULT_KEYMAP, DEFAULT_KEYMAP.with_entry(0, 5, Entry(152, 5)))
    with pytest.raises(KeymapError):
        DEFAULT_KEYMAP.with_entry(2, 0, Entry(0x41, 0))
    with pytest.raises(KeymapError):
        DEFAULT_KEYMAP.with_entry(0, 69, Entry(0x41, 0))
    with pytest.raises(KeymapError):
        Entry(256, 0)
    macro = DEFAULT_KEYMAP.with_entry(0, 7, Entry(152, 7))
    with pytest.raises(KeymapError):      # existing macro/DKS entries are never overwritten
        validate_change(macro, macro.with_entry(0, 7, Entry(0x41, 0)))
    # ... but they are carried through untouched
    other = macro.with_entry(0, 8, Entry(0x41, 0))
    assert len(validate_change(macro, other)) == 1


def test_unknown_entries_pass_through_unchanged():
    t = FakeTransport()
    t.keymap[2 * 10:2 * 10 + 2] = bytes([0xEE, 0x09])     # something we do not understand
    kb = KB65HE(t)
    kb.remap_key(3, "F5", layer=1)
    assert kb.read_keymap().get(0, 10) == Entry(0xEE, 9)
    assert t.keymap[20:22] == bytes([0xEE, 0x09])


def test_default_is_allowed_to_restore_special_codes():
    t = FakeTransport()
    t.keymap[2 * 41] = 0x41                                  # '#' key changed away from 0x16
    kb = KB65HE(t)
    kb.reset_keymap()
    assert bytes(t.keymap) == DEFAULT_KEYMAP.to_bytes()


# --- device -------------------------------------------------------------------
def test_read_keymap_via_fake_transport():
    kb, _ = make()
    assert kb.read_keymap() == DEFAULT_KEYMAP
    assert kb.keymap() == DEFAULT_KEYMAP.to_bytes()[:-4]   # firmware quirk: 272 bytes




def test_remap_key_roundtrip_both_layers():
    kb, t = make()
    after = kb.remap_key(21, "Z", layer=0)
    assert after.get(0, 21) == Entry(0x5A, 0)
    assert kb.read_keymap().get(1, 21) == DEFAULT_KEYMAP.get(1, 21)
    kb.remap_key(21, "F12", layer=1)
    km = kb.read_keymap()
    assert km.get(1, 21) == Entry(0x7B, 0)
    assert len(DEFAULT_KEYMAP.diff(km)) == 2
    kb.reset_keymap()
    assert kb.read_keymap() == DEFAULT_KEYMAP
    assert len(t.keymap_writes) == 3 and all(len(w) == 276 for w in t.keymap_writes)


def test_write_unchanged_block_is_a_valid_noop():
    kb, t = make()
    kb.write_keymap(kb.read_keymap())
    assert bytes(t.keymap) == DEFAULT_KEYMAP.to_bytes()
    assert len(t.keymap_writes) == 1


def test_invalid_change_sends_nothing():
    kb, t = make()
    with pytest.raises(KeymapError):
        kb.remap_key(64, "A", layer=0)
    with pytest.raises(KeymapError):
        kb.remap_key(3, 0x98, layer=0)
    with pytest.raises(KeymapError):
        kb.remap_key(3, "nope", layer=0)
    assert t.keymap_writes == []


def test_readback_mismatch_rolls_back_and_raises():
    kb, t = make()
    t.keymap_corrupt_next = 1                     # first write is stored wrongly
    with pytest.raises(KeymapVerifyError) as e:
        kb.remap_key(3, "F5", layer=1)
    assert "restored and verified" in str(e.value)
    assert kb.read_keymap() == DEFAULT_KEYMAP     # rollback worked
    assert len(t.keymap_writes) == 2


def test_readback_mismatch_with_failed_rollback_is_reported():
    kb, t = make()
    t.keymap_corrupt_next = 2                     # rollback is corrupted too
    with pytest.raises(KeymapVerifyError) as e:
        kb.remap_key(3, "F5", layer=1)
    assert "FAILED" in str(e.value)


def test_device_rejecting_the_write_raises_and_tries_rollback():
    from kb65he.protocol import DeviceStatusError
    kb, t = make()
    t.keymap_reject = True
    with pytest.raises(DeviceStatusError):
        kb.remap_key(3, "F5", layer=1)
    assert bytes(t.keymap) == DEFAULT_KEYMAP.to_bytes()


# --- backup before write -------------------------------------------------------
def test_backup_is_written_before_the_keymap(cfg):
    kb, t = make()
    backups = []
    profiles.write_keymap_safely(
        kb, DEFAULT_KEYMAP.with_entry(1, 3, Entry(0x74, 0)), backups=backups)
    assert len(backups) == 1
    path = backups[0]
    assert path.parent == cfg / "kb65he" / "backups" and path.name.startswith("keymap-")
    saved = profiles.read_file(path)
    assert saved["keymap_raw"] == DEFAULT_KEYMAP.to_bytes().hex()       # state BEFORE the write
    assert t.keymap[138 + 6:138 + 8] == bytes([0x74, 0])


def test_no_write_if_backup_fails(cfg, monkeypatch):
    kb, t = make()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(profiles, "write_file", boom)
    with pytest.raises(OSError):
        profiles.write_keymap_safely(
            kb, DEFAULT_KEYMAP.with_entry(1, 3, Entry(0x74, 0)))
    assert t.keymap_writes == []


def test_no_write_if_keymap_cannot_be_captured_for_backup(cfg, monkeypatch):
    kb, t = make()
    monkeypatch.setattr(profiles, "capture", lambda kb_, name: {"keymap_raw": None})
    with pytest.raises(profiles.ProfileError):
        profiles.write_keymap_safely(
            kb, DEFAULT_KEYMAP.with_entry(1, 3, Entry(0x74, 0)))
    assert t.keymap_writes == []




def test_backups_do_not_overwrite_each_other(cfg):
    kb, _ = make()
    a, b = profiles.backup_keymap(kb), profiles.backup_keymap(kb)
    assert a != b and a.exists() and b.exists()


# --- profiles -----------------------------------------------------------------
def test_profile_apply_never_touches_keymap_by_default(cfg):
    kb, t = make()
    prof = profiles.capture(kb, "x")
    assert profiles.apply(kb, prof) == ["trigger", "lighting"]
    assert t.keymap_writes == []


def test_profile_keymap_restore_makes_backup(cfg):
    kb, t = make()
    prof = profiles.capture(kb, "orig")
    kb.remap_key(3, "F5", layer=1)
    assert kb.read_keymap() != DEFAULT_KEYMAP
    backups = []
    assert profiles.apply(kb, prof, parts=("keymap",), backups=backups) == ["keymap"]
    assert kb.read_keymap() == DEFAULT_KEYMAP
    assert len(backups) == 1
    assert profiles.read_file(backups[0])["keymap_raw"] != prof["keymap_raw"]


def test_profile_keymap_errors_before_any_write(cfg):
    kb, t = make()
    prof = profiles.capture(kb, "x")
    kb.write_trigger({5: (1.0, 0.5)})
    bad = copy.deepcopy(prof)
    bad["keymap_raw"] = "00" * 10
    with pytest.raises(profiles.ProfileError):
        profiles.apply(kb, bad, parts=("trigger", "keymap"))
    assert kb.read_trigger()[5] == (10, 5)          # trigger part was not applied either
    bad["keymap_raw"] = None
    with pytest.raises(profiles.ProfileError):
        profiles.apply(kb, bad, parts=("keymap",))
    bad["keymap_raw"] = "not hex"
    with pytest.raises(profiles.ProfileError):
        profiles.validate(bad)


def test_old_version1_profiles_still_load(cfg, tmp_path):
    kb, _ = make()
    prof = profiles.capture(kb, "old")
    assert prof["version"] == 1
    legacy = {k: v for k, v in prof.items() if k != "keymap_raw"}      # oldest files had none
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy))
    loaded = profiles.read_file(p)
    assert profiles.apply(kb, loaded) == ["trigger", "lighting"]
    with pytest.raises(profiles.ProfileError):
        profiles.apply(kb, loaded, parts=("keymap",))


# --- CLI ------------------------------------------------------------------------
def test_cli_show_and_targets(capsys):
    cli_main(["--demo", "keymap"])
    out = capsys.readouterr().out
    assert "ESC" in out and "identical to the factory default" in out
    cli_main(["keymap", "targets"])
    assert "VOLUP" in capsys.readouterr().out




def test_cli_set_with_flag_makes_backup(capsys, cfg):
    cli_main(["--demo", "keymap", "set", "3", "F5", "--fn", "--experimental"])
    out = capsys.readouterr().out
    assert "verified by read-back" in out and "backup:" in out
    files = list((cfg / "kb65he" / "backups").glob("keymap-*.json"))
    assert len(files) == 1


def test_cli_friendly_errors(capsys, cfg):
    for argv, text in (
        (["keymap", "set", "3", "bogus"], "unknown or unsupported target"),
        (["keymap", "set", "999", "A"], "unknown key"),
        (["keymap", "set", "64", "A", "--experimental"], "Fn key"),
    ):
        with pytest.raises(SystemExit) as e:
            cli_main(["--demo", *argv])
        assert text in str(e.value)


def test_cli_rewrite_and_reset(capsys, cfg):
    cli_main(["--demo", "keymap", "rewrite"])
    cli_main(["--demo", "keymap", "reset-default", "--experimental"])
    assert len(list((cfg / "kb65he" / "backups").glob("keymap-*.json"))) == 2


# --- GUI ------------------------------------------------------------------------
def test_gui_keymap_page_edit(monkeypatch, cfg):
    pytest.importorskip("kb65he.gui.qt")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from kb65he.gui.app import MainWindow
    from kb65he.gui.qt import QApplication
    app = QApplication.instance() or QApplication([])
    w = MainWindow(demo=True)
    w.show_page("keymap")
    page = w.pages["keymap"]
    assert page.km == DEFAULT_KEYMAP and not page.view.assign      # base layer: nothing remapped
    page.set_layer(1)
    assert page.view.assign[1] == "F1"                               # Fn+1 = F1
    # Fn+G -> Pause
    page.view.set_selection({34})
    page.combo.setCurrentIndex(page.combo.findData(0x13))
    page.assign_selected()
    assert w.kb.read_keymap().get(1, 34) == Entry(0x13, 0)
    assert 34 in page.view.changed
    assert len(list((cfg / "kb65he" / "backups").glob("keymap-*.json"))) == 1
    # press-a-key capture: F5 (KEY_F5 = 63)
    page.capture_btn.setChecked(True)
    assert page.capture(63) and page.combo.currentData() == 0x74 and not page.capturing
    # the Fn key is locked
    page.set_layer(0)
    page.view.set_selection({64})
    assert not page.apply_btn.isEnabled()
    page.undo_last()
    assert w.kb.read_keymap() == DEFAULT_KEYMAP
    w.set_legends("uk")
    w.close()
    app.processEvents()


def test_gui_names():
    pytest.importorskip("kb65he.gui.qt")
    from kb65he.gui.keymap_page import function_for_evdev, long_name, short_name, target_groups
    assert long_name(0x59, "de") == "Z" and long_name(0x59, "uk") == "Y"   # VK_Y sits on the Z key (DE)
    assert short_name(0xA0, "de") == "Shift L"
    assert function_for_evdev(34) == 0x47 and function_for_evdev(119) == 0x13
    codes = [c for _, cs in target_groups("de") for c in cs]
    assert len(codes) == len(set(codes)) and set(codes) <= set(TARGETS)


def test_firmware_drops_last_four_bytes_on_read():
    """Real hardware returns 272 of 276 bytes (Fn layer keys 67/68 missing)."""
    from kb65he.keymap import DEFAULT_KEYMAP, KEYMAP_SIZE, Keymap
    kb = KB65HE(FakeTransport())
    assert len(kb.keymap()) == KEYMAP_SIZE - 4
    km = kb.read_keymap()                       # completed with the factory default
    assert km == DEFAULT_KEYMAP
    # a 272-byte backup (as saved by older builds) can still be parsed
    assert Keymap.from_bytes(DEFAULT_KEYMAP.to_bytes()[:-4]) == DEFAULT_KEYMAP
    # after a write the tool remembers what it wrote for the unreported entries
    changed = km.with_entry(1, 68, type(km.get(1, 68))(0x13, 0))   # Fn+Right -> Pause
    kb.write_keymap(changed)
    assert kb.read_keymap().get(1, 68).function == 0x13
