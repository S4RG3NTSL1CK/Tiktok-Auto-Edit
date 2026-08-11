# Dark theme with an indigo -> violet gradient accent, matching the app icon.

from ..paths import asset_path, base_dir  # noqa: F401 — re-exported for existing importers

INDIGO = "#4338CA"
VIOLET = "#9333EA"
INDIGO_HOVER = "#5346DD"
VIOLET_HOVER = "#A548F5"

QSS = f"""
QMainWindow, QDialog, #appDialog {{
    background-color: #0d0d14;
}}
QWidget {{
    background-color: transparent;
    color: #f0f0f5;
    font-size: 10.5pt;
}}
QLabel {{
    background: transparent;
    color: #f0f0f5;
}}

QGroupBox {{
    background-color: #16161f;
    border: 1px solid #2a2a38;
    border-radius: 10px;
    margin-top: 16px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 1px 6px;
    background-color: #0d0d14;
    border-radius: 4px;
    color: #c9b8ff;
}}

QPushButton {{
    background-color: #1e1e2a;
    color: #f0f0f5;
    border: 1px solid #2f2f40;
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{
    background-color: #262636;
    border-color: #3a3a4d;
}}
QPushButton:pressed {{
    background-color: #14141c;
}}
QPushButton:disabled {{
    color: #55556a;
    background-color: #16161f;
    border-color: #22222e;
}}

QPushButton[accent="true"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {INDIGO}, stop:1 {VIOLET});
    border: none;
    color: white;
    font-weight: 600;
    padding: 8px 16px;
}}
QPushButton[accent="true"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {INDIGO_HOVER}, stop:1 {VIOLET_HOVER});
}}
QPushButton[accent="true"]:pressed {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #372da3, stop:1 #7c28c2);
}}
QPushButton[accent="true"]:disabled {{
    background-color: #22222e;
    color: #55556a;
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: #1a1a24;
    border: 1px solid #2a2a38;
    border-radius: 6px;
    padding: 5px 8px;
    color: #f0f0f5;
    selection-background-color: {INDIGO};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {VIOLET};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: #55556a;
    background-color: #16161f;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: #1a1a24;
    border: 1px solid #2a2a38;
    selection-background-color: {INDIGO};
    color: #f0f0f5;
    outline: none;
}}

QCheckBox {{
    spacing: 8px;
    color: #f0f0f5;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #3a3a4d;
    border-radius: 4px;
    background: #1a1a24;
}}
QCheckBox::indicator:checked {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {INDIGO}, stop:1 {VIOLET});
    border: 1px solid {VIOLET};
}}
QCheckBox:disabled {{
    color: #55556a;
}}

QProgressBar {{
    background-color: #1a1a24;
    border: 1px solid #2a2a38;
    border-radius: 8px;
    text-align: center;
    color: #f0f0f5;
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {INDIGO}, stop:1 {VIOLET});
    border-radius: 7px;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: #2a2a38;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {INDIGO};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {INDIGO}, stop:1 {VIOLET});
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

QListWidget {{
    background-color: #16161f;
    border: 1px solid #2a2a38;
    border-radius: 8px;
    color: #f0f0f5;
    padding: 4px;
}}
QListWidget::item {{
    padding: 6px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {INDIGO}, stop:1 {VIOLET});
    color: white;
}}
QListWidget::item:hover:!selected {{
    background-color: #1e1e2a;
}}

QPlainTextEdit {{
    background-color: #0f0f16;
    border: 1px solid #2a2a38;
    border-radius: 8px;
    color: #b8b8c8;
    font-family: Consolas, "DejaVu Sans Mono", monospace;
}}

QSplitter::handle {{
    background-color: #2a2a38;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #33334a;
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #44445e;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: #33334a;
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QMenu {{
    background-color: #1a1a24;
    border: 1px solid #2a2a38;
    color: #f0f0f5;
}}
QMenu::item:selected {{
    background-color: {INDIGO};
}}

QToolTip {{
    background-color: #1e1e2a;
    color: #f0f0f5;
    border: 1px solid #3a3a4d;
    padding: 4px;
}}

QMessageBox {{
    background-color: #16161f;
}}
"""


def apply_theme(app) -> None:
    from PySide6.QtGui import QColor, QPalette

    palette = app.palette()
    palette.setColor(QPalette.Link, QColor(VIOLET))
    palette.setColor(QPalette.LinkVisited, QColor(VIOLET))
    app.setPalette(palette)

    app.setStyleSheet(QSS)


def style_dialog(dialog) -> None:
    """Top-level QDialog subclasses don't reliably paint a QSS
    `background-color` set via a `QDialog` type selector — confirmed on a
    real display, not just a headless quirk. An ID selector on the instance
    does work, so give every dialog the same object name and target that."""
    from PySide6.QtCore import Qt
    dialog.setAttribute(Qt.WA_StyledBackground, True)
    dialog.setObjectName("appDialog")


def mark_accent(button) -> None:
    """Gives a QPushButton the gradient primary-action look. Must be called
    after the global stylesheet is applied and before the button is shown,
    or followed by a style() unpolish/polish if toggled at runtime."""
    button.setProperty("accent", True)
