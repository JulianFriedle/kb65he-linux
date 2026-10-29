"""Colours and the application style sheet."""

BG = "#0d0e10"
SIDEBAR = "#111215"
SURFACE = "#16171b"
SURFACE_2 = "#1d1f24"
SURFACE_3 = "#25272d"
BORDER = "#24262c"
TEXT = "#e8e9ec"
MUTED = "#8b8e97"
FAINT = "#5b5e66"
ACCENT = "#5eead4"
ACCENT_TEXT = "#062b26"
DANGER = "#f87171"
OK = "#4ade80"

STYLE = f"""
* {{
    font-family: "Inter", "Noto Sans", "Cantarell", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel#appTitle {{ font-size: 15px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#appSubtitle {{ color: {FAINT}; font-size: 11px; }}
QLabel#pageTitle {{ font-size: 22px; font-weight: 600; }}
QLabel#pageSubtitle {{ color: {MUTED}; }}
QLabel#sectionLabel {{ color: {MUTED}; font-size: 11px; font-weight: 600;
    letter-spacing: 1px; text-transform: uppercase; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#faint {{ color: {FAINT}; font-size: 11px; }}
QLabel#bigValue {{ font-size: 28px; font-weight: 600; }}
QLabel#status {{ color: {MUTED}; font-size: 12px; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}

QPushButton#nav {{
    background: transparent; border: none; border-radius: 9px;
    padding: 9px 12px; text-align: left; color: {MUTED}; font-weight: 500;
}}
QPushButton#nav:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SURFACE_2}; color: {TEXT}; }}

QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #7ff0de; }}
QPushButton#primary:disabled {{ background: {SURFACE_3}; color: {FAINT}; }}
QPushButton#chip {{ border-radius: 9px; padding: 7px 12px; color: {MUTED}; }}
QPushButton#chip:checked {{ background: {ACCENT}; color: {ACCENT_TEXT}; border-color: {ACCENT}; }}

QSlider {{ min-height: 22px; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3}; border: none; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: {SURFACE_3}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; border: none; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::sub-page:horizontal:disabled {{ background: {FAINT}; }}

QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 6px 10px;
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_3};
    outline: none; padding: 4px;
}}
QLineEdit {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 12px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER}; selection-background-color: {SURFACE_3};
}}
QHeaderView::section {{
    background: {SURFACE_2}; color: {MUTED}; border: none; padding: 6px 10px; font-weight: 600;
}}
QFrame#divider {{ background: {BORDER}; border: none; }}
QMessageBox {{ background: {SURFACE}; }}
QMessageBox QLabel {{ font-size: 14px; padding: 6px 4px; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QLabel#toast {{
    background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 9px 16px; font-weight: 500;
}}
QLabel#code {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;
    font-family: "JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace; font-size: 12px;
}}
"""
