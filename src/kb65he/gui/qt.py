"""Qt binding shim: use PySide6 if installed (pip/pipx), otherwise PyQt6
(Debian/Ubuntu system package ``python3-pyqt6``)."""
from __future__ import annotations

import os

_forced = os.environ.get("KB65HE_QT", "").lower()  # "pyside6" or "pyqt6" for testing

if _forced != "pyqt6":
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401

        Signal = QtCore.Signal
        Property = QtCore.Property
        API = "PySide6"
    except ImportError:
        if _forced == "pyside6":
            raise
        QtCore = None  # type: ignore[assignment]

if _forced == "pyqt6" or QtCore is None:
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore[no-redef]  # noqa: F401

    Signal = QtCore.pyqtSignal  # type: ignore[attr-defined]
    Property = QtCore.pyqtProperty  # type: ignore[attr-defined]
    API = "PyQt6"

# re-export the classes the GUI uses
Qt = QtCore.Qt
QEasingCurve = QtCore.QEasingCurve
QEvent = QtCore.QEvent
QPointF = QtCore.QPointF
QPropertyAnimation = QtCore.QPropertyAnimation
QRectF = QtCore.QRectF
QSettings = QtCore.QSettings
QTimer = QtCore.QTimer

QColor = QtGui.QColor
QFont = QtGui.QFont
QIcon = QtGui.QIcon
QKeyEvent = QtGui.QKeyEvent
QPainter = QtGui.QPainter
QPainterPath = QtGui.QPainterPath
QPen = QtGui.QPen

_W = QtWidgets
QAbstractButton = _W.QAbstractButton
QAbstractItemView = _W.QAbstractItemView
QApplication = _W.QApplication
QButtonGroup = _W.QButtonGroup
QColorDialog = _W.QColorDialog
QComboBox = _W.QComboBox
QFileDialog = _W.QFileDialog
QFrame = _W.QFrame
QGraphicsOpacityEffect = _W.QGraphicsOpacityEffect
QGridLayout = _W.QGridLayout
QHeaderView = _W.QHeaderView
QHBoxLayout = _W.QHBoxLayout
QLabel = _W.QLabel
QLineEdit = _W.QLineEdit
QMainWindow = _W.QMainWindow
QMessageBox = _W.QMessageBox
QPushButton = _W.QPushButton
QSizePolicy = _W.QSizePolicy
QSlider = _W.QSlider
QStackedWidget = _W.QStackedWidget
QTableWidget = _W.QTableWidget
QTableWidgetItem = _W.QTableWidgetItem
QVBoxLayout = _W.QVBoxLayout
QWidget = _W.QWidget
