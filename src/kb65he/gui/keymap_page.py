"""Key map page: show and edit the assignment of the normal and the Fn layer."""
from __future__ import annotations

from .. import profiles
from ..device import KB65HE, NUM_KEYS
from ..keymap import (
    DEFAULT_KEYMAP,
    EVDEV_TO_FUNCTION,
    FN_KEY,
    PROTECTED_FUNCTIONS,
    TARGETS,
    VK_FN,
    Entry,
    Keymap,
    function_name,
)
from ..layout import EVDEV_TO_INDEX, KEY_BY_INDEX
from .i18n import tr
from .qt import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from .widgets import KeyboardView

# ---------------------------------------------------------------------------
# names
_BASE = DEFAULT_KEYMAP.layers[0]
# function -> physical key that sends it in the factory default (for layout legends)
VK_TO_KEY: dict[int, int] = {e.function: k for k, e in enumerate(_BASE) if e.function != VK_FN}

# long name (dropdown, tooltips), short name (drawn on the key cap); English, translated by tr()
_NAMES: dict[int, tuple[str, str]] = {
    0x13: ("Pause", "Pause"), 0x2C: ("Print", "Print"), 0x91: ("Scroll Lock", "Scroll"),
    0x90: ("Num Lock", "NumLk"), 0x2D: ("Insert", "Ins"), 0x24: ("Home", "Home"),
    0x5D: ("Menu", "Menu"), 0x5C: ("Win (right)", "Win R"), 0xC0: ("`", "`"),
    0x6A: ("Num *", "Num*"), 0x6B: ("Num +", "Num+"), 0x6D: ("Num -", "Num-"),
    0x6E: ("Num .", "Num."), 0x6F: ("Num /", "Num/"), 0x6C: ("Num Enter", "NumEnt"),
    173: ("Mute", "Mute"), 174: ("Volume down", "Vol-"), 175: ("Volume up", "Vol+"),
    176: ("Next track", "Next"), 177: ("Previous track", "Prev"), 179: ("Play/Pause", "Play"),
    181: ("Media player", "Media"),
    148: ("Lighting effect", "Effect"), 149: ("Lighting colour", "Colour"),
    204: ("Brightness up", "Light+"), 205: ("Brightness down", "Light-"),
    206: ("Speed up", "Speed+"), 207: ("Speed down", "Speed-"),
    1: ("Left click", "LMB"), 2: ("Right click", "RMB"), 4: ("Middle click", "MMB"),
    5: ("Mouse back", "M4"), 6: ("Mouse forward", "M5"),
    0xF4: ("Actuation mode (on-keyboard)", "Act."), VK_FN: ("Fn", "Fn"), 0x00: ("None", "–"),
}
for _i in range(10):
    _NAMES[0x60 + _i] = (f"Num {_i}", f"Num{_i}")
for _i in range(12):
    _NAMES[0x70 + _i] = (f"F{_i + 1}", f"F{_i + 1}")


def _legend(k: int, layout: str, short: bool = False) -> str:
    """Legend of physical key k, with left/right for the doubled modifiers."""
    if k == 62:
        return tr("Space")
    text = KEY_BY_INDEX[k].labels.get(layout, "")
    if k in (44, 59):
        text += " L" if short else " " + tr("L")
    elif k in (56, 65):
        text += " R" if short else " " + tr("R")
    return text


def long_name(function: int, layout: str) -> str:
    if function in VK_TO_KEY:
        return _legend(VK_TO_KEY[function], layout)
    if function in _NAMES:
        return tr(_NAMES[function][0])
    return function_name(function)


def short_name(function: int, layout: str) -> str:
    if function in VK_TO_KEY:
        return _legend(VK_TO_KEY[function], layout, short=True)
    if function in _NAMES:
        return tr(_NAMES[function][1])
    return function_name(function)


def target_groups(layout: str) -> list[tuple[str, list[int]]]:
    """Choices for the dropdown, grouped; every code is in TARGETS."""
    keys = [e.function for e in _BASE if e.function in TARGETS]
    seen = set(keys)
    other = [c for c, (_, kind) in TARGETS.items() if kind == "key" and c not in seen]
    order = list(range(0x70, 0x7C)) + [0x2C, 0x91, 0x13, 0x2D, 0x24, 0x5D, 0x5C, 0x90]
    other.sort(key=lambda c: (order.index(c) if c in order else 100, c))
    groups = [(tr("Keys of this keyboard"), keys), (tr("Other keys"), other)]
    for kind, title in (("media", "Media"), ("light", "Lighting"), ("mouse", "Mouse")):
        groups.append((tr(title), [c for c, (_, k) in TARGETS.items() if k == kind]))
    return groups


def function_for_evdev(code: int) -> int | None:
    """Function a pressed key (Linux KEY_* code) stands for, or None."""
    idx = EVDEV_TO_INDEX.get(code)
    if idx is not None and _BASE[idx].function in TARGETS:
        return _BASE[idx].function
    return EVDEV_TO_FUNCTION.get(code)


# ---------------------------------------------------------------------------
def _card():
    from .qt import QFrame
    f = QFrame()
    f.setObjectName("card")
    return f


def _label(text: str, name: str | None = None) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


class KeymapPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        self.km: Keymap | None = None
        self.layer = 0
        self.undo: list[Keymap] = []
        self.capturing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(_label(tr("Key map"), "pageTitle"))
        head.addWidget(_label(tr("Click a key, then choose what it should do. Changes are saved to the "
                                 "keyboard immediately, a backup is kept."), "pageSubtitle"))
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.layers = QButtonGroup(self)
        for i, text in enumerate((tr("Normal layer"), tr("Fn layer"))):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _c=False, i=i: self.set_layer(i))
            self.layers.addButton(b, i)
            bar.addWidget(b)
        bar.addSpacing(8)
        self.info = _label("", "muted")
        bar.addWidget(self.info)
        bar.addStretch(1)
        self.undo_btn = QPushButton(tr("Undo"))
        self.undo_btn.clicked.connect(self.undo_last)
        bar.addWidget(self.undo_btn)
        self.reset_all_btn = QPushButton(tr("Reset all…"))
        self.reset_all_btn.clicked.connect(self.reset_all)
        bar.addWidget(self.reset_all_btn)
        root.addLayout(bar)

        kb_card = _card()
        kb_box = QVBoxLayout(kb_card)
        kb_box.setContentsMargins(18, 18, 18, 18)
        self.view = KeyboardView("keymap")
        self.view.selectionChanged.connect(self._sel_changed)
        kb_box.addWidget(self.view)
        root.addWidget(kb_card)

        ctl = _card()
        row = QHBoxLayout(ctl)
        row.setContentsMargins(22, 18, 22, 18)
        row.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.key_title = _label("", "bigValue")
        self.key_detail = _label("", "muted")
        self.key_detail.setWordWrap(True)
        left.addWidget(self.key_title)
        left.addWidget(self.key_detail)
        left.addStretch(1)
        row.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(_label(tr("New function"), "sectionLabel"))
        pick = QHBoxLayout()
        pick.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.setMaxVisibleItems(18)
        pick.addWidget(self.combo, 1)
        self.capture_btn = QPushButton(tr("Press a key…"))
        self.capture_btn.setCheckable(True)
        self.capture_btn.toggled.connect(self._capture_toggled)
        pick.addWidget(self.capture_btn)
        right.addLayout(pick)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.apply_btn = QPushButton(tr("Assign"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setMinimumHeight(36)
        self.apply_btn.clicked.connect(self.assign_selected)
        self.default_btn = QPushButton(tr("Factory default for this key"))
        self.default_btn.clicked.connect(self.reset_key)
        btns.addWidget(self.apply_btn)
        btns.addWidget(self.default_btn)
        btns.addStretch(1)
        right.addLayout(btns)
        row.addLayout(right, 3)
        root.addWidget(ctl)

        hint = _label(tr("Names follow the key legends of the selected layout. The operating system's "
                         "keyboard layout decides which character a key types."), "faint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)
        self._fill_combo()
        self._sel_changed()

    # helpers ------------------------------------------------------------
    @property
    def layout_name(self) -> str:
        return getattr(self.w, "layout_name", "de")

    def _fill_combo(self):
        cur = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        for title, codes in target_groups(self.layout_name):
            self.combo.addItem(f"— {title} —")
            item = self.combo.model().item(self.combo.count() - 1)
            item.setEnabled(False)
            for c in codes:
                self.combo.addItem(long_name(c, self.layout_name), c)
        i = self.combo.findData(cur) if cur is not None else -1
        self.combo.setCurrentIndex(i if i >= 0 else 1)
        self.combo.blockSignals(False)

    def _locked_reason(self, layer: int, k: int) -> str | None:
        if self.km is None:
            return tr("Not connected")
        if k == FN_KEY:
            return tr("The Fn key cannot be remapped.")
        if self.km.get(layer, k).function in PROTECTED_FUNCTIONS:
            return tr("Holds a macro/DKS entry from the vendor software; not edited here.")
        return None

    def _selected(self) -> int | None:
        return next(iter(self.view.selected), None)

    def _refresh_view(self):
        v = self.view
        v.assign.clear()
        v.assign_tip.clear()
        v.changed.clear()
        v.locked = {FN_KEY}
        if self.km is None:
            v.update()
            return
        changed_total = len(DEFAULT_KEYMAP.diff(self.km))
        for k in range(NUM_KEYS):
            e = self.km.get(self.layer, k)
            default = DEFAULT_KEYMAP.get(self.layer, k)
            own = _BASE[k].function
            if e != default:
                v.changed.add(k)
            if e.function in PROTECTED_FUNCTIONS:
                v.locked.add(k)
            # only label keys that do something else than their legend says
            if e.function != own:
                v.assign[k] = short_name(e.function, self.layout_name)
            tip = f"#{k}  ·  {long_name(e.function, self.layout_name)}"
            if e != default:
                tip += "  ·  " + tr("factory default: {name}", name=long_name(default.function, self.layout_name))
            v.assign_tip[k] = tip
        v.update()
        self.info.setText(tr("Same as the factory default.") if not changed_total
                          else tr("{n} entries differ from the factory default.", n=changed_total))
        self.reset_all_btn.setEnabled(changed_total > 0)
        self.undo_btn.setEnabled(bool(self.undo))

    def _sel_changed(self):
        k = self._selected()
        layer_txt = tr("Normal layer") if self.layer == 0 else tr("Fn layer")
        if k is None or self.km is None:
            self.key_title.setText(tr("No key selected"))
            self.key_detail.setText(tr("Click a key on the keyboard above."))
            for b in (self.apply_btn, self.default_btn, self.capture_btn, self.combo):
                b.setEnabled(False)
            return
        e = self.km.get(self.layer, k)
        default = DEFAULT_KEYMAP.get(self.layer, k)
        prefix = "Fn + " if self.layer == 1 else ""
        self.key_title.setText(f"{prefix}{_legend(k, self.layout_name)}")
        lines = [f"{layer_txt} · #{k}",
                 tr("Now: {name}", name=long_name(e.function, self.layout_name)),
                 tr("Factory default: {name}", name=long_name(default.function, self.layout_name))]
        if self.layer == 1 and k in (67, 68):
            lines.append(tr("The keyboard does not report this entry; shown is the last written value."))
        reason = self._locked_reason(self.layer, k)
        if reason:
            lines.append(reason)
        self.key_detail.setText("\n".join(lines))
        ok = reason is None
        self.combo.setEnabled(ok)
        self.capture_btn.setEnabled(ok)
        self.apply_btn.setEnabled(ok)
        self.default_btn.setEnabled(ok and e != default)
        i = self.combo.findData(e.function)
        if i >= 0:
            self.combo.setCurrentIndex(i)

    # public -------------------------------------------------------------
    def set_layer(self, layer: int):
        self.layer = layer
        self.layers.button(layer).setChecked(True)
        self._refresh_view()
        self._sel_changed()

    def relabel(self):
        self.view.layout_name = self.layout_name
        self._fill_combo()
        self._refresh_view()
        self._sel_changed()

    def load(self, kb: KB65HE):
        try:
            self.km = kb.read_keymap()
        except Exception as e:  # noqa: BLE001 - the other pages must keep working
            self.km = None
            self.info.setText(tr("Could not read the key map: {err}", err=str(e)))
        self._refresh_view()
        self._sel_changed()

    # capture ------------------------------------------------------------
    def _capture_toggled(self, on: bool):
        self.capturing = on
        self.capture_btn.setText(tr("Press the key now… (Esc cancels)") if on else tr("Press a key…"))

    def capture(self, evdev_code: int) -> bool:
        """Called by the main window while capturing. Returns True if handled."""
        if not self.capturing:
            return False
        self.capture_btn.setChecked(False)
        if evdev_code == 1:          # Esc cancels (Esc itself can be picked from the list)
            return True
        func = function_for_evdev(evdev_code)
        i = self.combo.findData(func) if func is not None else -1
        if i < 0:
            self.w.toast.show_message(tr("This key cannot be assigned, pick it from the list."), error=True)
            return True
        self.combo.setCurrentIndex(i)
        return True

    # writes -------------------------------------------------------------
    def _write(self, new: Keymap, message: str, remember: bool = True) -> bool:
        kb = self.w.kb
        if kb is None or self.km is None:
            return False
        if new == self.km:
            self.w.toast.show_message(tr("No change"))
            return False
        before = self.km
        try:
            self.km = profiles.write_keymap_safely(kb, new)
        except Exception as e:  # noqa: BLE001
            self.w.on_error(e)
            try:
                self.km = kb.read_keymap()
            except Exception:  # noqa: BLE001
                pass
            self._refresh_view()
            self._sel_changed()
            return False
        if remember:
            self.undo.append(before)
            del self.undo[:-20]
        self._refresh_view()
        self._sel_changed()
        self.w.toast.show_message(message)
        return True

    def assign_selected(self):
        k = self._selected()
        func = self.combo.currentData()
        if k is None or func is None or self.km is None:
            return
        new = self.km.with_entry(self.layer, k, Entry(func, 0))
        prefix = "Fn + " if self.layer == 1 else ""
        self._write(new, tr("{key} now: {name}", key=prefix + _legend(k, self.layout_name),
                            name=long_name(func, self.layout_name)))

    def reset_key(self):
        k = self._selected()
        if k is None or self.km is None:
            return
        new = self.km.with_entry(self.layer, k, DEFAULT_KEYMAP.get(self.layer, k))
        self._write(new, tr("Factory default restored for this key"))

    def reset_all(self):
        if self.km is None or not self._confirm(
                tr("Restore the factory default for all keys on both layers?")):
            return
        self._write(DEFAULT_KEYMAP, tr("Factory default restored"))

    def undo_last(self):
        if not self.undo:
            return
        prev = self.undo.pop()
        if not self._write(prev, tr("Undone"), remember=False):
            self.undo.append(prev)
        self._refresh_view()

    def _confirm(self, text: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.standardButton(box.clickedButton()) == QMessageBox.StandardButton.Yes


__all__ = ["KeymapPage", "long_name", "short_name", "target_groups", "function_for_evdev"]
