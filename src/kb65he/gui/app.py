"""Main window."""
from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QSettings, Qt, QTimer
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
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..device import (
    BRIGHTNESS_MAX,
    KB65HE,
    LIGHT_EFFECTS,
    NUM_KEYS,
    SPEED_MAX,
    BootloaderMode,
    DeviceNotFound,
    FakeTransport,
    Lighting,
    find_devices,
)
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
        root.addLayout(page_header(tr("Actuation point"), tr("Click keys to select them, then apply a value.")))

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
        root.addLayout(bar)

        ctl = card()
        cbox = QHBoxLayout(ctl)
        cbox.setContentsMargins(22, 18, 22, 18)
        cbox.setSpacing(22)
        vcol = QVBoxLayout()
        vcol.setSpacing(2)
        vcol.addWidget(label(tr("Actuation point"), "sectionLabel"))
        self.value_label = label("1.0 mm", "bigValue")
        vcol.addWidget(self.value_label)
        cbox.addLayout(vcol)

        scol = QVBoxLayout()
        scol.setSpacing(6)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 40)
        self.slider.setValue(10)
        self.slider.valueChanged.connect(lambda v: self.value_label.setText(f"{v / 10:.1f} mm"))
        scol.addStretch(1)
        scol.addWidget(self.slider)
        hints = QHBoxLayout()
        hints.addWidget(label("0.1 mm · " + tr("more sensitive"), "faint"))
        hints.addStretch(1)
        hints.addWidget(label(tr("deeper") + " · 4.0 mm", "faint"))
        scol.addLayout(hints)
        scol.addStretch(1)
        cbox.addLayout(scol, 1)

        self.apply_btn = QPushButton(tr("Apply to selection"))
        self.apply_btn.setObjectName("primary")
        self.apply_btn.setMinimumHeight(40)
        self.apply_btn.clicked.connect(self.apply)
        cbox.addWidget(self.apply_btn)
        root.addWidget(ctl)
        root.addStretch(1)
        self._sel_changed()

    def _sel_changed(self):
        n = len(self.view.selected)
        self.sel_label.setText(tr("{n} selected", n=n))
        self.apply_btn.setEnabled(n > 0)
        vals = {round(self.view.values.get(k, 0), 1) for k in self.view.selected}
        if len(vals) == 1 and next(iter(vals)) > 0:
            self.slider.setValue(round(next(iter(vals)) * 10))

    def load(self, kb: KB65HE):
        self.view.values = kb.read_actuation()
        self.view.update()

    def apply(self):
        kb = self.w.kb
        if kb is None or not self.view.selected:
            return
        mm = self.slider.value() / 10
        keys = sorted(self.view.selected)
        try:
            kb.write_actuation({k: mm for k in keys})
            self.view.values = kb.read_actuation()
            self.view.update()
            self.w.toast.show_message(tr("{n} keys set to {mm} mm", n=len(keys), mm=f"{mm:.1f}"))
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
            "device": DevicePage(self),
        }
        self.not_connected = NotConnectedPage()
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.stack.addWidget(self.not_connected)

        self.nav = QButtonGroup(self)
        for key, title in [("actuation", tr("Actuation")), ("lighting", tr("Lighting")), ("device", tr("Device"))]:
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
