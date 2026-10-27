"""Main window."""
from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, profiles
from ..device import (
    BRIGHTNESS_MAX,
    KB65HE,
    LIGHT_EFFECTS,
    NUM_KEYS,
    RT_OFF,
    SPEED_MAX,
    BootloaderMode,
    DeviceNotFound,
    FakeTransport,
    Lighting,
    find_devices,
)
from ..layout import EVDEV_TO_INDEX
from . import theme
from .i18n import tr
from .widgets import KeyboardView, Swatch, Toast, Toggle

WASD = {17, 30, 31, 32}
UDEV_HINT = (
    "sudo cp udev/70-kb65he.rules /etc/udev/rules.d/\n"
    "sudo udevadm control --reload-rules && sudo udevadm trigger"
)


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def label(text: str, name: str | None = None) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


def page_header(title: str, subtitle: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(4)
    box.addWidget(label(title, "pageTitle"))
    box.addWidget(label(subtitle, "pageSubtitle"))
    return box


# ---------------------------------------------------------------------------
class ActuationPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addLayout(page_header(tr("Actuation"), tr("Click keys to select them, then apply a value.")))

        kb_card = card()
        kb_box = QVBoxLayout(kb_card)
        kb_box.setContentsMargins(18, 18, 18, 18)
        self.view = KeyboardView("actuation")
        self.view.selectionChanged.connect(self._sel_changed)
        kb_box.addWidget(self.view)
        root.addWidget(kb_card)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        for text, fn in [
            (tr("All"), lambda: self.view.set_selection(range(NUM_KEYS))),
            (tr("None"), lambda: self.view.set_selection([])),
            (tr("Invert"), lambda: self.view.set_selection(set(range(NUM_KEYS)) - self.view.selected)),
            (tr("WASD"), lambda: self.view.set_selection(WASD)),
        ]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.sel_label = label("", "muted")
        bar.addSpacing(8)
        bar.addWidget(self.sel_label)
        bar.addStretch(1)
        bar.addWidget(label(tr("Show"), "faint"))
        self.display = QButtonGroup(self)
        for i, (text, mode) in enumerate([(tr("Actuation point"), "actuation"), (tr("Rapid Trigger"), "rt")]):
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _c=False, m=mode: self._set_display(m))
            self.display.addButton(b, i)
            bar.addWidget(b)
        root.addLayout(bar)

        ctl = card()
        grid = QGridLayout(ctl)
        grid.setContentsMargins(22, 18, 22, 18)
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(14)

        # row 0: actuation point
        self.value_label = label("1.0 mm", "bigValue")
        self.slider = self._slider(grid, 0, tr("Actuation point"), self.value_label,
                                   "0.1 mm · " + tr("more sensitive"), tr("deeper") + " · 4.0 mm", 1, 40)
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(f"{v / 10:.1f} mm"))

        # row 1: rapid trigger
        self.rt_label = label("0.3 mm", "bigValue")
        self.rt_toggle = Toggle()
        self.rt_slider = self._slider(grid, 1, tr("Rapid Trigger"), self.rt_label,
                                      "0.1 mm · " + tr("more sensitive"), tr("less sensitive") + " · 3.9 mm",
                                      1, 39, self.rt_toggle)
        self.rt_slider.setValue(3)
        self.rt_slider.valueChanged.connect(self._rt_text)
        self.rt_toggle.toggled.connect(self._rt_text)
        self.rt_toggle.setChecked(True)

        self.apply_btn = QPushButton(tr("Apply to selection"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setMinimumHeight(40)
        self.apply_btn.clicked.connect(self.apply)
        grid.addWidget(self.apply_btn, 0, 2, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(1, 1)
        root.addWidget(ctl)
        rt_hint = label(tr("Rapid Trigger: the key re-triggers as soon as it moves this far down or up, "
                           "instead of waiting for the fixed actuation point."), "faint")
        rt_hint.setWordWrap(True)
        root.addWidget(rt_hint)
        root.addStretch(1)
        self._sel_changed()

    def _slider(self, grid, row, title, value_label, lo, hi, vmin, vmax, toggle=None) -> QSlider:
        head = QVBoxLayout()
        head.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(label(title, "sectionLabel"))
        if toggle is not None:
            top.addWidget(toggle)
        top.addStretch(1)
        head.addLayout(top)
        value_label.setMinimumWidth(130)
        head.addWidget(value_label)
        grid.addLayout(head, row, 0)
        col = QVBoxLayout()
        col.setSpacing(6)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(vmin, vmax)
        s.setValue(10)
        col.addStretch(1)
        col.addWidget(s)
        hints = QHBoxLayout()
        hints.addWidget(label(lo, "faint"))
        hints.addStretch(1)
        hints.addWidget(label(hi, "faint"))
        col.addLayout(hints)
        col.addStretch(1)
        grid.addLayout(col, row, 1)
        return s

    def _set_display(self, mode):
        self.view.display = mode
        self.view.update()

    def _rt_text(self, *_):
        on = self.rt_toggle.isChecked()
        self.rt_slider.setEnabled(on)
        self.rt_label.setText(f"{self.rt_slider.value() / 10:.1f} mm" if on else tr("Off"))

    def _sel_changed(self):
        n = len(self.view.selected)
        self.sel_label.setText(tr("{n} selected", n=n))
        self.apply_btn.setEnabled(n > 0)
        sel = [k for k in self.view.selected if k in self.view.values]
        acts = {round(self.view.values[k], 1) for k in sel}
        if len(acts) == 1:
            self.slider.setValue(round(acts.pop() * 10))
        rts = {round(self.view.rt.get(k, 0), 1) for k in sel}
        if len(rts) == 1:
            v = rts.pop()
            self.rt_toggle.setChecked(v < RT_OFF)
            if v < RT_OFF:
                self.rt_slider.setValue(round(v * 10))
            self._rt_text()

    def load(self, kb: KB65HE):
        trig = kb.read_trigger()
        self.view.values = {k: a / 10 for k, (a, _) in trig.items()}
        self.view.rt = {k: b / 10 for k, (_, b) in trig.items()}
        self.view.update()

    def apply(self):
        kb = self.w.kb
        if kb is None or not self.view.selected:
            return
        act = self.slider.value() / 10
        rt = self.rt_slider.value() / 10 if self.rt_toggle.isChecked() else RT_OFF
        keys = sorted(self.view.selected)
        try:
            kb.write_trigger({k: (act, rt) for k in keys})
            self.load(kb)
            self.w.toast.show_message(tr("{n} keys saved", n=len(keys)))
        except Exception as e:  # noqa: BLE001
            self.w.on_error(e)


# ---------------------------------------------------------------------------
class LightingPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        self.lighting = Lighting()
        self._loading = False
        self._write_timer = QTimer(self)
        self._write_timer.setSingleShot(True)
        self._write_timer.setInterval(220)
        self._write_timer.timeout.connect(self._write)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addLayout(page_header(tr("Lighting"), tr("Changes are written to the keyboard immediately.")))

        kb_card = card()
        kb_box = QVBoxLayout(kb_card)
        kb_box.setContentsMargins(18, 18, 18, 18)
        self.view = KeyboardView("lighting")
        self.view.setMinimumHeight(180)
        kb_box.addWidget(self.view)
        root.addWidget(kb_card)

        row = QHBoxLayout()
        row.setSpacing(18)

        # left: switch, brightness, speed
        left = card()
        lbox = QVBoxLayout(left)
        lbox.setContentsMargins(22, 18, 22, 18)
        lbox.setSpacing(14)
        on_row = QHBoxLayout()
        on_row.addWidget(label(tr("Backlight")))
        on_row.addStretch(1)
        self.toggle = Toggle()
        self.toggle.toggled.connect(self._changed)
        on_row.addWidget(self.toggle)
        lbox.addLayout(on_row)

        self.bright = self._slider_row(lbox, tr("Brightness"), BRIGHTNESS_MAX)
        self.speed = self._slider_row(lbox, tr("Speed"), SPEED_MAX)
        lbox.addStretch(1)
        row.addWidget(left, 2)

        # right: effects and colours
        right = card()
        rbox = QVBoxLayout(right)
        rbox.setContentsMargins(22, 18, 22, 18)
        rbox.setSpacing(12)
        rbox.addWidget(label(tr("Effect"), "sectionLabel"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.effects = QButtonGroup(self)
        self.effects.setExclusive(True)
        for i, name in enumerate(LIGHT_EFFECTS):
            b = QPushButton(tr(name))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.effects.addButton(b, i)
            grid.addWidget(b, i // 4, i % 4)
        self.effects.idClicked.connect(lambda _i: self._changed())
        rbox.addLayout(grid)

        rbox.addSpacing(6)
        rbox.addWidget(label(tr("Colour"), "sectionLabel"))
        sw_row = QHBoxLayout()
        sw_row.setSpacing(4)
        self.swatches = QButtonGroup(self)
        self.swatches.setExclusive(True)
        for i in range(7):
            s = Swatch(QColor("#ffffff"))
            s.doubleClicked.connect(lambda i=i: self._edit_colour(i))
            self.swatches.addButton(s, i)
            sw_row.addWidget(s)
        sw_row.addStretch(1)
        self.swatches.idClicked.connect(lambda _i: self._changed())
        rbox.addLayout(sw_row)
        rbox.addWidget(label(tr("Click a swatch to make it active, double-click to edit."), "faint"))
        rbox.addStretch(1)
        row.addWidget(right, 3)
        root.addLayout(row, 1)

    def _slider_row(self, box: QVBoxLayout, title: str, maximum: int) -> QSlider:
        head = QHBoxLayout()
        head.addWidget(label(title, "sectionLabel"))
        head.addStretch(1)
        val = label("", "muted")
        head.addWidget(val)
        box.addLayout(head)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, maximum)
        s.valueChanged.connect(lambda v: val.setText(f"{v}/{maximum}"))
        s.valueChanged.connect(lambda _v: self._changed())
        box.addWidget(s)
        return s

    def load(self, kb: KB65HE):
        self.lighting = kb.read_lighting()
        self._loading = True
        li = self.lighting
        self.toggle.setChecked(li.on)
        self.bright.setValue(min(li.brightness, BRIGHTNESS_MAX))
        self.speed.setValue(min(li.speed, SPEED_MAX))
        b = self.effects.button(li.effect)
        if b:
            b.setChecked(True)
        for i, c in enumerate(li.colors):
            sw = self.swatches.button(i)
            sw.color = QColor(*c)
            sw.update()
        if self.swatches.button(li.color_index):
            self.swatches.button(li.color_index).setChecked(True)
        self._loading = False
        self._preview()

    def _edit_colour(self, i: int):
        sw = self.swatches.button(i)
        c = QColorDialog.getColor(sw.color, self, tr("Colour"))
        if c.isValid():
            sw.color = c
            sw.setChecked(True)
            sw.update()
            self._changed()

    def _collect(self):
        li = self.lighting
        li.on = self.toggle.isChecked()
        li.brightness = self.bright.value()
        li.speed = self.speed.value()
        if self.effects.checkedId() >= 0:
            li.effect = self.effects.checkedId()
        if self.swatches.checkedId() >= 0:
            li.color_index = self.swatches.checkedId()
        li.colors = [(s.color.red(), s.color.green(), s.color.blue())
                     for s in (self.swatches.button(i) for i in range(7))]

    def _preview(self):
        self._collect()
        li = self.lighting
        self.view.lit = li.on
        self.view.tint = QColor(*li.colors[li.color_index]) if li.color_index < 7 else QColor(theme.ACCENT)
        self.view.tint_strength = 0.25 + 0.75 * li.brightness / BRIGHTNESS_MAX
        self.view.update()

    def _changed(self, *_):
        if self._loading:
            return
        self._preview()
        self._write_timer.start()

    def _write(self):
        if self.w.kb is None:
            return
        try:
            self.w.kb.write_lighting(self.lighting)
        except Exception as e:  # noqa: BLE001
            self.w.on_error(e)


# ---------------------------------------------------------------------------
class ProfilesPage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addLayout(page_header(tr("Profiles"),
                                   tr("Save the current keyboard settings and load them again later.")))

        new = card()
        nbox = QHBoxLayout(new)
        nbox.setContentsMargins(22, 16, 22, 16)
        nbox.setSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("Name, e.g. Gaming"))
        self.name_edit.returnPressed.connect(self.save_current)
        nbox.addWidget(self.name_edit, 1)
        save_btn = QPushButton(tr("Save current settings"))
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save_current)
        nbox.addWidget(save_btn)
        imp = QPushButton(tr("Import…"))
        imp.clicked.connect(self.import_file)
        nbox.addWidget(imp)
        root.addWidget(new)

        self.list_card = card()
        self.list_box = QVBoxLayout(self.list_card)
        self.list_box.setContentsMargins(8, 8, 8, 8)
        self.list_box.setSpacing(0)
        root.addWidget(self.list_card)
        hint = label(tr("Profiles contain actuation points, rapid trigger and lighting. Stored in {path}",
                        path=str(profiles.profile_dir())), "faint")
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(hint)
        root.addStretch(1)
        self.refresh()

    def load(self, _kb: KB65HE):
        self.refresh()

    def refresh(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            wdg = item.widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        items = profiles.list_profiles()
        if not items:
            empty = label(tr("No profiles yet."), "muted")
            empty.setContentsMargins(14, 12, 14, 12)
            self.list_box.addWidget(empty)
            return
        for i, prof in enumerate(items):
            if i:
                line = QFrame()
                line.setObjectName("divider")
                line.setFixedHeight(1)
                self.list_box.addWidget(line)
            self.list_box.addWidget(self._row(prof))

    def _row(self, prof: dict) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = label(prof.get("name", "?"))
        name.setStyleSheet("font-weight: 600;")
        text.addWidget(name)
        created = str(prof.get("created", ""))[:16].replace("T", " ")
        text.addWidget(label(f"{profiles.summary(prof, tr)}   ·   {created}", "faint"))
        h.addLayout(text, 1)
        for title, fn, primary in ((tr("Load"), self.apply, True), (tr("Export…"), self.export, False),
                                   (tr("Delete"), self.delete, False)):
            b = QPushButton(title)
            if primary:
                b.setObjectName("primary")
            b.clicked.connect(lambda _c=False, p=prof, f=fn: f(p))
            h.addWidget(b)
        return row

    # actions -------------------------------------------------------------
    def save_current(self):
        name = self.name_edit.text().strip()
        if not name:
            self.w.toast.show_message(tr("Enter a name first"), error=True)
            self.name_edit.setFocus()
            return
        if self.w.kb is None:
            return
        try:
            if profiles.path_for(name).exists() and not self._confirm(
                    tr("Overwrite profile \u201c{name}\u201d?", name=name)):
                return
            profiles.save(profiles.capture(self.w.kb, name))
            self.name_edit.clear()
            self.refresh()
            self.w.toast.show_message(tr("Profile \u201c{name}\u201d saved", name=name))
        except Exception as e:  # noqa: BLE001
            self.w.on_error(e)

    def apply(self, prof: dict):
        if self.w.kb is None:
            return
        try:
            profiles.apply(self.w.kb, prof)
            self.w.reload_pages()
            self.w.toast.show_message(tr("Profile \u201c{name}\u201d loaded", name=prof.get("name", "")))
        except Exception as e:  # noqa: BLE001
            self.w.on_error(e)

    def export(self, prof: dict):
        default = os.path.join(os.path.expanduser("~"), os.path.basename(prof["_path"]))
        path, _ = QFileDialog.getSaveFileName(self, tr("Export profile"), default, "JSON (*.json)")
        if not path:
            return
        data = {k: v for k, v in prof.items() if not k.startswith("_")}
        try:
            profiles.write_file(data, path)
            self.w.toast.show_message(tr("Exported to {path}", path=path))
        except OSError as e:
            self.w.on_error(e)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import profile"), os.path.expanduser("~"), "JSON (*.json)")
        if not path:
            return
        try:
            prof = profiles.read_file(path)
            name = prof.get("name") or os.path.splitext(os.path.basename(path))[0]
            prof["name"] = name
            if profiles.path_for(name).exists() and not self._confirm(
                    tr("Overwrite profile \u201c{name}\u201d?", name=name)):
                return
            profiles.save(prof)
            self.refresh()
            self.w.toast.show_message(tr("Profile \u201c{name}\u201d imported", name=name))
        except (profiles.ProfileError, OSError) as e:
            self.w.toast.show_message(f"{tr('Error')}: {e}", error=True)

    def delete(self, prof: dict):
        name = prof.get("name", "")
        if not self._confirm(tr("Delete profile \u201c{name}\u201d?", name=name)):
            return
        try:
            os.remove(prof["_path"])
        except OSError as e:
            self.w.on_error(e)
        self.refresh()

    def _confirm(self, text: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes


# ---------------------------------------------------------------------------
class DevicePage(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.w = window
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        root.addLayout(page_header(tr("Device"), f"kb65he-linux {__version__}"))
        c = card()
        grid = QGridLayout(c)
        grid.setContentsMargins(22, 18, 22, 18)
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(12)
        self.fields = {}
        for r, name in enumerate(["Model", "Interface", "Serial", "Revision"]):
            grid.addWidget(label(tr(name), "muted"), r, 0)
            v = label("–")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(v, r, 1)
            self.fields[name] = v
        grid.addWidget(label(tr("Legends"), "muted"), 4, 0)
        self.legends = QComboBox()
        self.legends.addItems(["Deutsch (ISO-DE)", "English (ISO-UK)"])
        self.legends.setCurrentIndex(0 if window.settings.value("legends", "de") == "de" else 1)
        self.legends.currentIndexChanged.connect(self._legends)
        grid.addWidget(self.legends, 4, 1, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(1, 1)
        root.addWidget(c)
        root.addWidget(label(tr("Unofficial tool, not affiliated with Endgame Gear. Use at your own risk."), "faint"))
        root.addStretch(1)

    def _legends(self, i):
        name = "de" if i == 0 else "uk"
        self.w.settings.setValue("legends", name)
        self.w.set_legends(name)

    def load(self, kb: KB65HE):
        self.fields["Model"].setText(kb.info.name if kb.info else tr("Demo mode"))
        self.fields["Interface"].setText(kb.info.path if kb.info else "–")
        self.fields["Serial"].setText(kb.serial() or "–")
        self.fields["Revision"].setText(str(kb.revision()))


# ---------------------------------------------------------------------------
class NotConnectedPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.addStretch(1)
        box = QVBoxLayout()
        box.setSpacing(10)
        box.addWidget(label(tr("Keyboard not found"), "pageTitle"))
        hint = label(tr("Plug in the KB65HE 8k. If it is connected, install the udev rule so your user can access it:"), "pageSubtitle")
        hint.setWordWrap(True)
        box.addWidget(hint)
        code = label(UDEV_HINT, "code")
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(code)
        self.detail = label("", "faint")
        box.addWidget(self.detail)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        inner = QWidget()
        inner.setLayout(box)
        inner.setMaximumWidth(560)
        wrap.addWidget(inner)
        wrap.addStretch(1)
        root.addLayout(wrap)
        root.addStretch(2)


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo = demo
        self.kb: KB65HE | None = None
        self.settings = QSettings("kb65he-linux", "kb65he")
        self.setWindowTitle("KB65HE")
        self.resize(1180, 760)
        self.setMinimumSize(900, 620)

        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(210)
        sbox = QVBoxLayout(side)
        sbox.setContentsMargins(14, 22, 14, 18)
        sbox.setSpacing(4)
        sbox.addWidget(label("KB65HE", "appTitle"))
        sbox.addWidget(label("Linux configurator", "appSubtitle"))
        sbox.addSpacing(22)

        self.stack = QStackedWidget()
        self.pages = {
            "actuation": ActuationPage(self),
            "lighting": LightingPage(self),
            "profiles": ProfilesPage(self),
            "device": DevicePage(self),
        }
        self.not_connected = NotConnectedPage()
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.stack.addWidget(self.not_connected)

        self.nav = QButtonGroup(self)
        for key, title in [("actuation", tr("Actuation")), ("lighting", tr("Lighting")),
                           ("profiles", tr("Profiles")), ("device", tr("Device"))]:
            b = QPushButton(title)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            self.nav.addButton(b)
            sbox.addWidget(b)
            setattr(self, f"nav_{key}", b)
        sbox.addStretch(1)
        self.status = label("", "status")
        sbox.addWidget(self.status)

        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.toast = Toast(self.stack)
        self.current = "actuation"
        self.set_legends(self.settings.value("legends", "de"))

        self.pressed: set[int] = set()
        QApplication.instance().installEventFilter(self)

        self.poll = QTimer(self)
        self.poll.setInterval(2000)
        self.poll.timeout.connect(self.check_connection)
        self.poll.start()
        self.check_connection()

    # navigation ---------------------------------------------------------
    def show_page(self, key: str):
        self.current = key
        getattr(self, f"nav_{key}").setChecked(True)
        if self.kb is not None:
            self.stack.setCurrentWidget(self.pages[key])

    def set_legends(self, name: str):
        self.pages["actuation"].view.layout_name = name
        self.pages["lighting"].view.layout_name = name
        self.pages["actuation"].view.update()
        self.pages["lighting"].view.update()

    def reload_pages(self):
        if self.kb is None:
            return
        try:
            for p in self.pages.values():
                p.load(self.kb)
        except Exception as e:  # noqa: BLE001
            self.on_error(e)

    # live key highlighting ----------------------------------------------
    def _views(self):
        return (self.pages["actuation"].view, self.pages["lighting"].view)

    def _set_pressed(self, keys: set[int]):
        self.pressed = keys
        for v in self._views():
            v.pressed = keys
            v.update()

    def eventFilter(self, obj, event):
        et = event.type()
        if et in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and self.isActiveWindow():
            if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
                return False
            if isinstance(QApplication.focusWidget(), QLineEdit):
                return False
            idx = EVDEV_TO_INDEX.get(event.nativeScanCode() - 8)
            if idx is None:
                return False
            if not event.isAutoRepeat():
                keys = set(self.pressed)
                (keys.add if et == QEvent.Type.KeyPress else keys.discard)(idx)
                self._set_pressed(keys)
            return True  # keep keys from triggering buttons/sliders while testing
        if et == QEvent.Type.ApplicationDeactivate and self.pressed:
            self._set_pressed(set())
        return False

    # connection ---------------------------------------------------------
    def _set_status(self, connected: bool, text: str):
        dot = theme.OK if connected else theme.FAINT
        self.status.setText(f'<span style="color:{dot}">●</span>&nbsp; {text}')

    def check_connection(self):
        if self.kb is not None:
            if self.kb.info and not os.path.exists(self.kb.info.path):
                self.disconnect()
            return
        detail = ""
        try:
            if self.demo:
                self.kb = KB65HE(FakeTransport())
            else:
                self.kb = KB65HE.open()
        except (DeviceNotFound, BootloaderMode) as e:
            detail = str(e)
        except PermissionError:
            devs = find_devices()
            detail = tr("Permission denied on {path}", path=devs[0].path if devs else "/dev/hidraw*")
        except OSError as e:
            detail = str(e)
        if self.kb is None:
            self.not_connected.detail.setText(detail)
            self.stack.setCurrentWidget(self.not_connected)
            self._set_status(False, tr("Not connected"))
            return
        try:
            for p in self.pages.values():
                p.load(self.kb)
        except Exception as e:  # noqa: BLE001
            self.on_error(e)
            return
        self._set_status(True, tr("Demo mode") if self.demo else tr("Connected"))
        self.show_page(self.current)

    def disconnect(self):
        if self.kb is not None:
            try:
                self.kb.close()
            except OSError:
                pass
        self.kb = None
        self.stack.setCurrentWidget(self.not_connected)
        self._set_status(False, tr("Not connected"))

    def on_error(self, e: Exception):
        self.toast.show_message(f"{tr('Error')}: {e}", error=True)
        if isinstance(e, OSError) and not isinstance(e, TimeoutError):
            self.disconnect()


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(prog="kb65he-gui")
    ap.add_argument("--demo", action="store_true", help="run with a simulated keyboard")
    a, rest = ap.parse_known_args(argv)
    app = QApplication([sys.argv[0], *rest])
    app.setApplicationName("kb65he")
    app.setDesktopFileName("kb65he")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLE)
    icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    w = MainWindow(demo=a.demo)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
