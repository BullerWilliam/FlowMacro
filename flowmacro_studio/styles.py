from __future__ import annotations

from PySide6.QtGui import QColor

from .models import PORT_COLORS

WINDOW_STYLESHEET = """
QMainWindow, QWidget {
    background: #f3f6fb;
    color: #31415f;
    font-family: "Segoe UI", "Arial", "Tahoma";
    font-size: 9pt;
}
QWidget#AppShell {
    background: #eef3fb;
}
QFrame#ToolBarFrame {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #4c97ff,
        stop: 0.6 #4280e3,
        stop: 1 #3d6fdb
    );
    border-bottom: 1px solid #78a8f3;
}
QFrame#ToolStrip {
    background: transparent;
    border: none;
    border-radius: 0;
}
QLabel#BrandTitle {
    color: white;
    font-size: 13pt;
    font-weight: 700;
}
QLabel#ProjectPill {
    background: rgba(255, 255, 255, 0.18);
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 14px;
    color: #f5fbff;
    padding: 6px 12px;
    font-family: "Segoe UI", "Arial", "Tahoma";
    font-weight: 700;
}
QPushButton#HeaderNavButton {
    background: transparent;
    border: none;
    border-radius: 12px;
    color: white;
    font-weight: 700;
    padding: 8px 12px;
}
QPushButton#HeaderNavButton:hover {
    background: rgba(255, 255, 255, 0.15);
}
QPushButton#HeaderActionButton {
    background: rgba(255, 255, 255, 0.16);
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 14px;
    color: white;
    padding: 8px 14px;
    font-weight: 700;
}
QPushButton#HeaderActionButton:hover {
    background: rgba(255, 255, 255, 0.22);
}
QLabel#DrawerTitle, QLabel#ConsoleTitle, QLabel#PanelTitle {
    color: #1f2f4d;
    font-size: 10.5pt;
    font-weight: 700;
}
QLabel#DrawerMuted, QLabel#PanelMuted {
    color: #6d7fa6;
    font-size: 8.8pt;
}
QFrame#InspectorGroup {
    background: white;
    border: 1px solid #d8e1f1;
    border-radius: 16px;
}
QLabel#InspectorGroupTitle {
    color: #223454;
    font-size: 9.8pt;
    font-weight: 700;
}
QLabel#InspectorGroupMeta {
    color: #4c97ff;
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 0.08em;
}
QFrame#LibraryPanel, QFrame#InspectorPanel, QFrame#StagePanel, QFrame#NodeShelf, QFrame#ConsoleTray, QFrame#CanvasStage {
    background: #ffffff;
    border: 1px solid #d7e1f2;
    border-radius: 18px;
}
QFrame#LibraryPanel {
    border-right: 1px solid #d7e1f2;
}
QFrame#InspectorPanel {
    border-left: 1px solid #d7e1f2;
}
QFrame#ConsoleTray {
    background: #ffffff;
}
QFrame#DrawerHeader, QFrame#ConsoleHeader, QFrame#CanvasHeader, QFrame#StageHeader, QFrame#ShelfHeader {
    background: transparent;
    border: none;
}
QFrame#CanvasSurface {
    background: #f5f7fc;
    border: 1px solid #d7e1f2;
    border-radius: 16px;
}
QFrame#CanvasControls {
    background: rgba(255, 255, 255, 0.96);
    border: 1px solid #d7e1f2;
    border-radius: 18px;
}
QLabel#OverlayError {
    background: #ffeff2;
    border: 1px solid #ffb5c1;
    border-radius: 14px;
    color: #b23855;
    font-size: 9pt;
    font-weight: 700;
    padding: 10px 14px;
}
QLineEdit, QPlainTextEdit, QTextEdit, QTreeWidget, QSpinBox, QDoubleSpinBox, QComboBox, QScrollArea {
    background: white;
    border: 1px solid #ccd7ea;
    border-radius: 14px;
    padding: 7px 9px;
    color: #2f4164;
    selection-background-color: #cfe4ff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QTreeWidget:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #4c97ff;
}
QPlainTextEdit#ConsoleOutput, QTextEdit#ConsoleOutput {
    border-radius: 16px;
    font-family: "Consolas", "Courier New";
    font-size: 8.8pt;
    background: #fbfcff;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d3ddf0;
    border-radius: 14px;
    color: #294064;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: #f7fbff;
    border-color: #9fc3fb;
}
QPushButton:pressed {
    background: #edf4ff;
}
QPushButton#ToolbarButton {
    min-height: 34px;
}
QPushButton#ToolbarToggle {
    min-height: 34px;
    background: #eaf2ff;
}
QPushButton#ToolbarToggle:checked {
    background: #4c97ff;
    border-color: #4c97ff;
    color: white;
}
QPushButton#PrimaryButton {
    background: #4cbf56;
    border-color: #3aa646;
    color: white;
}
QPushButton#PrimaryButton:hover {
    background: #42b74d;
}
QPushButton#DangerButton {
    background: #f26f7e;
    border-color: #ea5f70;
    color: white;
}
QPushButton#DangerButton:hover {
    background: #ea6373;
}
QToolButton#CanvasToolButton {
    background: white;
    border: 1px solid #d3ddf0;
    border-radius: 18px;
    color: #42628f;
    padding: 5px 8px;
    min-width: 38px;
    min-height: 38px;
    font-weight: 700;
}
QToolButton#CanvasToolButton:hover {
    background: #f7fbff;
    border-color: #9fc3fb;
}
QPushButton#CategoryButton {
    background: transparent;
    border: none;
    border-radius: 16px;
    color: #567199;
    padding: 8px 6px;
    font-weight: 700;
    text-align: center;
}
QPushButton#CategoryButton:hover {
    background: #eef5ff;
}
QPushButton#CategoryButton:checked {
    background: #dcecff;
    color: #2358a8;
}
QFrame#CategoryRail {
    background: #edf4ff;
    border: 1px solid #d7e1f2;
    border-radius: 16px;
}
QWidget#BlockScrollContent {
    background: transparent;
}
QPushButton#PaletteBlockCard {
    background: white;
    border: 1px solid #d7e1f2;
    border-radius: 18px;
    color: #2d4164;
    text-align: left;
    padding: 12px 14px;
    font-weight: 700;
}
QPushButton#PaletteBlockCard:hover {
    background: #f8fbff;
    border-color: #9fc3fb;
}
QLabel#StageStatus {
    background: #eef5ff;
    border: 1px solid #d3e1fb;
    border-radius: 12px;
    color: #37609e;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#StagePlaceholder {
    background: #ffffff;
    border: 1px solid #d7e1f2;
    border-radius: 16px;
    color: #7084a6;
}
QFrame#NodeShelfCard {
    background: #f7faff;
    border: 1px solid #d7e1f2;
    border-radius: 14px;
}
QFrame#NodeShelfCard[selected="true"] {
    background: #e6f1ff;
    border: 2px solid #4c97ff;
}
QHeaderView::section {
    background: #f1f6ff;
    color: #58759e;
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
    background: #dcecff;
}
QTreeWidget::item:hover {
    background: #eff6ff;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 3px;
}
QScrollBar::handle {
    background: #c9d7ee;
    border-radius: 5px;
    min-height: 20px;
    min-width: 20px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
}
QToolTip {
    background: white;
    color: #304260;
    border: 1px solid #bfd1ec;
    padding: 6px;
}
QCheckBox {
    color: #31415f;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #afc2df;
    background: white;
}
QCheckBox::indicator:checked {
    background: #4c97ff;
    border-color: #4c97ff;
}
"""


def port_color(type_name: str) -> QColor:
    return QColor(PORT_COLORS.get(type_name, "#9fb3d1"))


def with_alpha(color: QColor, alpha: int) -> QColor:
    tinted = QColor(color)
    tinted.setAlpha(alpha)
    return tinted
