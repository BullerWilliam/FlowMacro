from __future__ import annotations

from PySide6.QtGui import QColor

from .models import PORT_COLORS

WINDOW_STYLESHEET = """
QMainWindow, QWidget {
    background: #08111c;
    color: #dbe8ff;
    font-family: "Segoe UI", "Arial", "Tahoma";
    font-size: 9pt;
}
QWidget#AppShell {
    background: #08111c;
}
QFrame#ToolBarFrame {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #0b1625,
        stop: 0.55 #0c1c2e,
        stop: 1 #0b1726
    );
    border-bottom: 1px solid rgba(86, 132, 188, 0.32);
}
QFrame#ToolStrip {
    background: rgba(11, 21, 36, 0.86);
    border: 1px solid rgba(71, 111, 164, 0.34);
    border-radius: 12px;
}
QLabel#BrandTitle {
    color: #f5faff;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#ProjectPill {
    background: rgba(21, 42, 72, 0.72);
    border: 1px solid rgba(89, 144, 214, 0.34);
    border-radius: 11px;
    color: #a8c9f7;
    padding: 4px 10px;
    font-family: "Consolas", "Courier New";
}
QLabel#DrawerTitle, QLabel#ConsoleTitle, QLabel#PanelTitle {
    color: #f0f6ff;
    font-size: 10pt;
    font-weight: 700;
}
QLabel#DrawerMuted, QLabel#PanelMuted {
    color: #6f91bf;
    font-size: 8.6pt;
}
QFrame#DrawerPanel, QFrame#LibraryPanel, QFrame#InspectorPanel {
    background: rgba(8, 15, 26, 0.96);
    border: 1px solid rgba(64, 100, 148, 0.24);
}
QFrame#LibraryPanel {
    border-right: 1px solid rgba(76, 118, 176, 0.34);
}
QFrame#InspectorPanel {
    border-left: 1px solid rgba(76, 118, 176, 0.34);
}
QFrame#ConsoleTray {
    background: rgba(7, 14, 24, 0.98);
    border-top: 1px solid rgba(77, 121, 183, 0.36);
}
QFrame#DrawerHeader, QFrame#ConsoleHeader {
    background: transparent;
    border: none;
}
QFrame#CanvasStage {
    background: #08111c;
}
QFrame#CanvasControls {
    background: rgba(9, 19, 33, 0.84);
    border: 1px solid rgba(93, 143, 212, 0.32);
    border-radius: 13px;
}
QLabel#OverlayError {
    background: rgba(92, 18, 31, 0.96);
    border: 1px solid rgba(255, 125, 140, 0.88);
    border-radius: 12px;
    color: #ffdbe0;
    font-size: 9pt;
    font-weight: 700;
    padding: 9px 14px;
}
QLineEdit, QPlainTextEdit, QTreeWidget, QSpinBox, QDoubleSpinBox, QComboBox, QScrollArea {
    background: rgba(8, 17, 29, 0.96);
    border: 1px solid rgba(53, 84, 126, 0.46);
    border-radius: 10px;
    padding: 7px 9px;
    color: #e2eeff;
    selection-background-color: #225ba5;
}
QLineEdit:focus, QPlainTextEdit:focus, QTreeWidget:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: rgba(88, 164, 248, 0.92);
}
QPlainTextEdit#ConsoleOutput {
    border-radius: 12px;
    font-family: "Consolas", "Courier New";
    font-size: 8.8pt;
}
QPushButton {
    background: rgba(17, 35, 58, 0.9);
    border: 1px solid rgba(69, 110, 168, 0.46);
    border-radius: 10px;
    color: #e9f3ff;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: rgba(24, 48, 79, 0.94);
    border-color: rgba(106, 162, 232, 0.68);
}
QPushButton:pressed {
    background: rgba(29, 59, 95, 0.98);
}
QPushButton#ToolbarButton {
    min-height: 30px;
}
QPushButton#ToolbarToggle {
    min-height: 30px;
    background: rgba(10, 22, 36, 0.78);
}
QPushButton#ToolbarToggle:checked {
    background: rgba(25, 57, 99, 0.92);
    border-color: rgba(96, 174, 248, 0.92);
    color: #ffffff;
}
QPushButton#PrimaryButton {
    background: rgba(18, 83, 162, 0.96);
    border-color: rgba(98, 176, 247, 0.92);
}
QPushButton#PrimaryButton:hover {
    background: rgba(28, 102, 194, 0.98);
}
QPushButton#DangerButton {
    background: rgba(73, 20, 33, 0.92);
    border-color: rgba(151, 58, 74, 0.82);
}
QPushButton#DangerButton:hover {
    background: rgba(98, 28, 44, 0.96);
}
QToolButton#CanvasToolButton {
    background: rgba(18, 35, 58, 0.9);
    border: 1px solid rgba(72, 114, 172, 0.52);
    border-radius: 9px;
    color: #e5f0ff;
    padding: 5px 8px;
    min-width: 36px;
    min-height: 26px;
    font-weight: 700;
}
QToolButton#CanvasToolButton:hover {
    background: rgba(26, 50, 82, 0.96);
    border-color: rgba(101, 170, 247, 0.84);
}
QHeaderView::section {
    background: rgba(11, 20, 33, 0.94);
    color: #6f91bf;
    border: none;
    padding: 6px;
}
QTreeWidget {
    outline: none;
}
QTreeWidget::item {
    padding: 4px 6px;
    border-radius: 6px;
}
QTreeWidget::item:selected {
    background: rgba(25, 58, 101, 0.94);
}
QTreeWidget::item:hover {
    background: rgba(62, 109, 174, 0.16);
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 3px;
}
QScrollBar::handle {
    background: rgba(56, 88, 128, 0.8);
    border-radius: 5px;
    min-height: 20px;
    min-width: 20px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
}
QToolTip {
    background: rgba(7, 14, 24, 0.98);
    color: #edf5ff;
    border: 1px solid rgba(81, 129, 194, 0.54);
    padding: 6px;
}
QCheckBox {
    color: #dbe8ff;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid rgba(71, 109, 158, 0.58);
    background: rgba(10, 19, 32, 0.96);
}
QCheckBox::indicator:checked {
    background: rgba(55, 132, 220, 0.96);
    border-color: rgba(106, 174, 247, 0.92);
}
"""


def port_color(type_name: str) -> QColor:
    return QColor(PORT_COLORS.get(type_name, "#9fb3d1"))


def with_alpha(color: QColor, alpha: int) -> QColor:
    tinted = QColor(color)
    tinted.setAlpha(alpha)
    return tinted
