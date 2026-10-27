"""Custom widgets: keyboard view, toggle switch, colour swatch, toast."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget

from ..layout import ENTER_INDEX, ENTER_TOP, HEIGHT_U, KEYS, WIDTH_U
from . import theme


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class KeyboardView(QWidget):
    """Draws the 69-key ISO layout.

    mode "actuation": keys show their actuation value and can be selected.
    mode "lighting":  keys are tinted with a colour (preview only).
    """

    selectionChanged = Signal()

    GAP = 0.09  # key gap in units

    def __init__(self, mode: str = "actuation", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.layout_name = "de"
        self.values: dict[int, float] = {}
        self.rt: dict[int, float] = {}
        self.display = "actuation"  # or "rt"
        self.selected: set[int] = set()
        self.tint = QColor(theme.ACCENT)
        self.tint_strength = 1.0
        self.lit = True
        self._hover: int | None = None
        self._drag_value: bool | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        pol = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        pol.setHeightForWidth(True)
        self.setSizePolicy(pol)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * HEIGHT_U / WIDTH_U)

    # geometry ----------------------------------------------------------
    def _unit(self) -> tuple[float, float, float]:
        u = min(self.width() / WIDTH_U, self.height() / HEIGHT_U)
        ox = (self.width() - u * WIDTH_U) / 2
        oy = (self.height() - u * HEIGHT_U) / 2
        return u, ox, oy

    @staticmethod
    def _rounded_polygon(points, r) -> QPainterPath:
        path = QPainterPath()
        n = len(points)
        for i in range(n):
            prev, cur, nxt = points[i - 1], points[i], points[(i + 1) % n]
            def towards(a, b, d):
                dx, dy = b.x() - a.x(), b.y() - a.y()
                ln = max((dx * dx + dy * dy) ** 0.5, 1e-6)
                d = min(d, ln / 2)
                return QPointF(a.x() + dx / ln * d, a.y() + dy / ln * d)
            p1, p2 = towards(cur, prev, r), towards(cur, nxt, r)
            if i == 0:
                path.moveTo(p1)
            else:
                path.lineTo(p1)
            path.quadTo(cur, p2)
        path.closeSubpath()
        return path

    def _key_path(self, key, u, ox, oy) -> QPainterPath:
        g = self.GAP * u / 2
        r = u * 0.14
        if key.index == ENTER_INDEX:
            tx, ty, tw = ENTER_TOP
            x0, x1 = ox + tx * u + g, ox + (tx + tw) * u - g
            xb = ox + key.x * u + g
            y0, y1, y2 = oy + ty * u + g, oy + (ty + 1) * u - g, oy + (key.y + 1) * u - g
            pts = [QPointF(x0, y0), QPointF(x1, y0), QPointF(x1, y2), QPointF(xb, y2),
                   QPointF(xb, y1), QPointF(x0, y1)]
            return self._rounded_polygon(pts, r)
        path = QPainterPath()
        path.addRoundedRect(QRectF(ox + key.x * u + g, oy + key.y * u + g, key.w * u - 2 * g, u - 2 * g), r, r)
        return path

    def _key_at(self, pos) -> int | None:
        u, ox, oy = self._unit()
        for key in KEYS:
            if self._key_path(key, u, ox, oy).contains(QPointF(pos)):
                return key.index
        return None

    # painting ----------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        u, ox, oy = self._unit()
        base = QColor(theme.SURFACE_2)
        accent = QColor(theme.ACCENT)
        label_font = QFont(self.font())
        label_font.setPixelSize(max(9, int(u * 0.2)))
        value_font = QFont(self.font())
        value_font.setPixelSize(max(9, int(u * 0.22)))
        value_font.setWeight(QFont.Weight.DemiBold)

        for key in KEYS:
            path = self._key_path(key, u, ox, oy)
            rect = path.boundingRect()
            sel = key.index in self.selected
            hover = key.index == self._hover

            if self.mode == "actuation":
                v = self.values.get(key.index)
                # 0.1 mm -> strong tint, 4.0 mm -> none
                t = 0.0 if v is None else (4.0 - v) / 3.9 * 0.08
                fill = _mix(base, accent, t + (0.26 if sel else 0.0))
            else:
                fill = _mix(base, self.tint, 0.42 * self.tint_strength) if self.lit else base
            if hover:
                fill = fill.lighter(118)
            p.fillPath(path, fill)

            pen = QPen(QColor(theme.ACCENT) if sel else QColor(theme.BORDER))
            pen.setWidthF(2.0 if sel else 1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            legend = key.labels.get(self.layout_name, "")
            text_col = QColor(theme.TEXT) if (sel or self.mode == "lighting") else QColor(theme.MUTED)
            p.setPen(text_col)
            p.setFont(label_font)
            pad = u * 0.14
            if key.index == ENTER_INDEX:
                lrect = QRectF(ox + ENTER_TOP[0] * u + pad, oy + ENTER_TOP[1] * u + pad, ENTER_TOP[2] * u, u)
            else:
                lrect = rect.adjusted(pad, pad * 0.8, -pad, -pad)
            p.drawText(lrect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, legend)

            if self.mode == "actuation" and key.index in self.values:
                p.setFont(value_font)
                p.setPen(QColor(theme.TEXT))
                vrect = rect.adjusted(pad, pad, -pad, -pad * 0.8)
                rt = self.rt.get(key.index)
                if self.display == "rt":
                    txt = "–" if rt is None or rt >= 4.0 else f"{rt:.1f}"
                else:
                    txt = f"{self.values[key.index]:.1f}"
                p.drawText(vrect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, txt)
                if rt is not None and rt < 4.0:
                    d = max(4.0, u * 0.09)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(theme.ACCENT))
                    p.drawEllipse(QRectF(rect.right() - pad - d, rect.top() + pad, d, d))
        p.end()

    # interaction -------------------------------------------------------
    def mousePressEvent(self, e):
        if self.mode != "actuation" or e.button() != Qt.MouseButton.LeftButton:
            return
        k = self._key_at(e.position())
        if k is None:
            return
        self._drag_value = k not in self.selected
        self._apply(k)

    def mouseMoveEvent(self, e):
        k = self._key_at(e.position())
        if k != self._hover:
            self._hover = k
            self.setToolTip(self._tooltip(k))
            if self.mode == "actuation":
                self.setCursor(Qt.CursorShape.PointingHandCursor if k is not None else Qt.CursorShape.ArrowCursor)
            self.update()
        if self._drag_value is not None and k is not None:
            self._apply(k)

    def _tooltip(self, k) -> str:
        if k is None or self.mode != "actuation" or k not in self.values:
            return ""
        rt = self.rt.get(k)
        rt_txt = "off" if rt is None or rt >= 4.0 else f"{rt:.1f} mm"
        return f"#{k}  ·  {self.values[k]:.1f} mm  ·  RT {rt_txt}"

    def mouseReleaseEvent(self, _e):
        self._drag_value = None

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def _apply(self, k: int):
        before = k in self.selected
        if self._drag_value and not before:
            self.selected.add(k)
        elif not self._drag_value and before:
            self.selected.discard(k)
        else:
            return
        self.update()
        self.selectionChanged.emit()

    def set_selection(self, keys):
        self.selected = set(keys)
        self.update()
        self.selectionChanged.emit()


class Toggle(QAbstractButton):
    """iOS-style switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, on):  # keep knob in sync without animation
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = _mix(QColor(theme.SURFACE_3), QColor(theme.ACCENT), self._pos)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
        p.setBrush(QColor("#ffffff"))
        x = 3 + self._pos * (self.width() - self.height())
        p.drawEllipse(QRectF(x, 3, self.height() - 6, self.height() - 6))
        p.end()


class Swatch(QAbstractButton):
    doubleClicked = Signal()

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.color = color
        self.setCheckable(True)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, _e):
        self.doubleClicked.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isChecked():
            p.setPen(QPen(QColor(theme.TEXT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
        p.setPen(QPen(QColor(0, 0, 0, 80), 1))
        p.setBrush(self.color)
        p.drawEllipse(QRectF(6, 6, self.width() - 12, self.height() - 12))
        p.end()


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, error: bool = False):
        self.setText(text)
        self.setStyleSheet(f"color: {theme.DANGER};" if error else "")
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 24)
        self.raise_()
        self.show()
        self._timer.start(2600)
