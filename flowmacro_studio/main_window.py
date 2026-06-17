from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QParallelAnimationGroup,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QColor, QCursor, QDrag, QFont, QGuiApplication, QPainter, QPalette, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .canvas import NODE_MIME_TYPE, NodeItem, NodeScene, NodeView
from .inspector import InspectorPanel
from .models import ConnectionModel, GraphModel, NodeDefinition, NodeModel
from .node_definitions import build_node_catalog
from .runtime import GraphRuntime, _release_all_held_inputs
from .storage import load_graph, save_graph
from .styles import WINDOW_STYLESHEET


class ExecutionThread(QThread):
    log_message = Signal(object)
    run_failed = Signal(str)
    run_succeeded = Signal()

    def __init__(
        self,
        graph: GraphModel,
        catalog: dict[str, NodeDefinition],
        project_path: Path | None,
    ) -> None:
        super().__init__()
        self.graph = graph
        self.catalog = catalog
        self.project_path = project_path
        self.stop_event = Event()

    def run(self) -> None:
        runtime = GraphRuntime(
            graph=self.graph,
            catalog=self.catalog,
            project_path=self.project_path,
            log=self.log_message.emit,
            should_stop=self.stop_event.is_set,
        )
        try:
            runtime.run()
        except Exception as exc:  # noqa: BLE001
            self.run_failed.emit(str(exc))
            return
        self.run_succeeded.emit()

    def stop(self) -> None:
        self.stop_event.set()


class AnimatedDock(QFrame):
    def __init__(self, orientation: str, expanded_size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self.expanded_size = expanded_size
        self._open = False
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)

        if self.orientation == "width":
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.setMinimumWidth(0)
            self.setMaximumWidth(0)
            properties = (b"minimumWidth", b"maximumWidth")
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumHeight(0)
            self.setMaximumHeight(0)
            properties = (b"minimumHeight", b"maximumHeight")

        self._animation_group = QParallelAnimationGroup(self)
        self._animations: list[QPropertyAnimation] = []
        for prop in properties:
            animation = QPropertyAnimation(self, prop, self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            self._animation_group.addAnimation(animation)
            self._animations.append(animation)

    def current_extent(self) -> int:
        return self.width() if self.orientation == "width" else self.height()

    def set_open(self, is_open: bool, animate: bool = True) -> None:
        target = self.expanded_size if is_open else 0
        current = self.current_extent()
        self._open = is_open

        if not animate or current == target:
            self._apply_extent(target)
            return

        self._animation_group.stop()
        for animation in self._animations:
            animation.setStartValue(current)
            animation.setEndValue(target)
        self._animation_group.start()

    def is_open(self) -> bool:
        return self._open

    def _apply_extent(self, value: int) -> None:
        if self.orientation == "width":
            self.setMinimumWidth(value)
            self.setMaximumWidth(value)
        else:
            self.setMinimumHeight(value)
            self.setMaximumHeight(value)


class RuntimeConsole(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConsoleOutput")
        self.setReadOnly(True)
        self.setAcceptRichText(True)
        self.setPlaceholderText("Runtime logs appear here during macro execution.")
        self.document().setMaximumBlockCount(800)

    def append_entry(self, value: object) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if not self.document().isEmpty():
            cursor.insertBlock()

        if isinstance(value, dict) and value.get("kind") in {"image", "stage_image"}:
            label = "[Stage] Image" if value.get("kind") == "stage_image" else "[Print] Image"
            cursor.insertHtml(f'<span style="color:#8fb5eb;">{label}</span><br>')
            if value.get("path"):
                image_path = Path(str(value["path"])).resolve()
                image_uri = QUrl.fromLocalFile(str(image_path)).toString()
                cursor.insertHtml(f'<img src="{image_uri}" width="340" /><br>')
                cursor.insertHtml(
                    f'<span style="color:#a8c9f7;font-family:Consolas;">{escape(str(image_path))}</span>'
                )
            elif value.get("data_base64"):
                encoded = base64.b64encode(base64.b64decode(str(value["data_base64"]))).decode("ascii")
                cursor.insertHtml(f'<img src="data:image/png;base64,{encoded}" width="340" /><br>')
                cursor.insertHtml('<span style="color:#a8c9f7;font-family:Consolas;">in-memory image</span>')
            else:
                cursor.insertText(json.dumps(value, indent=2))
        else:
            if isinstance(value, (dict, list, tuple)):
                text = json.dumps(value, indent=2)
            else:
                text = str(value)
            cursor.insertText(text)

        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class ScreenPositionPicker(QWidget):
    position_picked = Signal(int, int)
    picker_closed = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self._cursor_pos = QCursor.pos()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self._set_virtual_geometry()

    def _set_virtual_geometry(self) -> None:
        geometry = QRect()
        for screen in QGuiApplication.screens():
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(3, 8, 16, 70))

        box = QRect(0, 0, 420, 82)
        box.moveCenter(self.rect().center())
        box.translate(0, -120)
        painter.setPen(QColor("#5faeff"))
        painter.setBrush(QColor(7, 16, 28, 228))
        painter.drawRoundedRect(box, 14, 14)

        painter.setPen(QColor("#f4fbff"))
        title_font = painter.font()
        title_font.setPointSize(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(box.adjusted(16, 14, -16, -36), Qt.AlignLeft | Qt.AlignVCenter, "Pick Screen Position")

        painter.setPen(QColor("#9dbce6"))
        body_font = painter.font()
        body_font.setPointSize(9)
        body_font.setBold(False)
        painter.setFont(body_font)
        message = (
            f"Click anywhere on the screen to capture X/Y.\n"
            f"Current cursor: ({self._cursor_pos.x()}, {self._cursor_pos.y()})    Esc cancels"
        )
        painter.drawText(box.adjusted(16, 36, -16, -12), Qt.TextWordWrap, message)

    def mouseMoveEvent(self, event) -> None:
        self._cursor_pos = event.globalPosition().toPoint()
        self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            point = event.globalPosition().toPoint()
            self.position_picked.emit(point.x(), point.y())
            self.close()
            return
        if event.button() == Qt.RightButton:
            self.close()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.picker_closed.emit()
        super().closeEvent(event)


class CanvasStage(QFrame):
    def __init__(self, view: NodeView) -> None:
        super().__init__()
        self.setObjectName("CanvasStage")
        self.view = view

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("CanvasHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        tab_strip = QFrame()
        tab_strip.setObjectName("EditorTabStrip")
        tab_layout = QHBoxLayout(tab_strip)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(6)

        for label, active in [("Code", True)]:
            button = QPushButton(label)
            button.setObjectName("EditorTabActive" if active else "EditorTab")
            button.setFlat(True)
            tab_layout.addWidget(button)

        subtitle = QLabel("Drag blocks here to build your FlowMacro script.")
        subtitle.setObjectName("DrawerMuted")
        header_layout.addWidget(tab_strip)
        header_layout.addWidget(subtitle, 1)
        layout.addWidget(header)

        self.surface = QFrame()
        self.surface.setObjectName("CanvasSurface")
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(0)
        surface_layout.addWidget(self.view)
        layout.addWidget(self.surface, 1)

        self.error_toast = QLabel(self.surface)
        self.error_toast.setObjectName("OverlayError")
        self.error_toast.setWordWrap(True)
        self.error_toast.hide()

        self.controls = QFrame(self.surface)
        self.controls.setObjectName("CanvasControls")
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(6)

        self.zoom_in_button = self._create_canvas_button("+", "Zoom in")
        self.zoom_out_button = self._create_canvas_button("-", "Zoom out")
        self.reset_zoom_button = self._create_canvas_button("100%", "Reset zoom")
        self.fit_view_button = self._create_canvas_button("Fit", "Fit all blocks")

        controls_layout.addWidget(self.zoom_in_button)
        controls_layout.addWidget(self.zoom_out_button)
        controls_layout.addWidget(self.reset_zoom_button)
        controls_layout.addWidget(self.fit_view_button)

        self.zoom_out_button.clicked.connect(self.view.zoom_out)
        self.zoom_in_button.clicked.connect(self.view.zoom_in)
        self.reset_zoom_button.clicked.connect(self.view.reset_zoom)
        self.fit_view_button.clicked.connect(self.view.fit_content)

    def _create_canvas_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton(self.controls)
        button.setObjectName("CanvasToolButton")
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def show_error(self, message: str) -> None:
        self.error_toast.setText(message)
        self.error_toast.show()
        self.error_toast.raise_()
        self._position_overlays()
        QTimer.singleShot(2600, self.error_toast.hide)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        self.controls.adjustSize()
        controls_margin = 16
        self.controls.move(
            self.surface.width() - self.controls.width() - controls_margin,
            self.surface.height() - self.controls.height() - controls_margin,
        )
        self.controls.raise_()

        if self.error_toast.isHidden():
            return

        toast_width = min(520, max(260, self.surface.width() - 40))
        self.error_toast.setFixedWidth(toast_width)
        self.error_toast.adjustSize()
        self.error_toast.move((self.surface.width() - self.error_toast.width()) // 2, 16)

CATEGORY_ORDER = ["Control", "Input", "Screen", "Files", "Logic", "Variables"]

CATEGORY_META = {
    "Control": {"label": "Control", "hint": "Start, timing, and flow", "color": "#ffab19"},
    "Input": {"label": "Input", "hint": "Mouse and keyboard actions", "color": "#4c97ff"},
    "Screen": {"label": "Screen", "hint": "Screenshots and pixels", "color": "#ff6680"},
    "Files": {"label": "Files", "hint": "Read, write, move, delete", "color": "#ffbf00"},
    "Logic": {"label": "Logic", "hint": "Compare, math, text, booleans", "color": "#59c059"},
    "Variables": {"label": "Variables", "hint": "Store values and read them later", "color": "#ff8c1a"},
}


class BlockCardButton(QPushButton):
    activated = Signal(str)

    def __init__(self, definition: NodeDefinition) -> None:
        super().__init__()
        self.definition = definition
        self._press_pos = QPoint()
        description = definition.description
        if len(description) > 64:
            description = f"{description[:61]}..."
        self.setObjectName("PaletteBlockCard")
        self.setText(f"{definition.title}\n{description}")
        self.setToolTip(definition.description)
        self.setCursor(Qt.OpenHandCursor)
        self.setMinimumHeight(78)
        self.setStyleSheet(
            "QPushButton#PaletteBlockCard {"
            f"border-left: 10px solid {definition.color};"
            "padding-left: 14px;"
            "}"
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        mime_data = QMimeData()
        mime_data.setData(NODE_MIME_TYPE, self.definition.type_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.CopyAction)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.definition.type_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class StagePreview(QFrame):
    run_requested = Signal()
    stop_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StagePanel")
        self._preview_pixmap: QPixmap | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("StageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        stage_pill = QLabel("Stage")
        stage_pill.setObjectName("StageTitlePill")
        subtitle = QLabel("Preview")
        subtitle.setObjectName("DrawerMuted")
        header_layout.addWidget(stage_pill)
        header_layout.addWidget(subtitle, 1)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("PrimaryButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.setEnabled(False)
        header_layout.addWidget(self.run_button)
        header_layout.addWidget(self.stop_button)
        layout.addWidget(header)

        self.status_label = QLabel("Ready to run")
        self.status_label.setObjectName("StageStatus")
        layout.addWidget(self.status_label)

        self.preview_label = QLabel("Use Set Stage to preview an image here.")
        self.preview_label.setObjectName("StagePlaceholder")
        self.preview_label.setMinimumHeight(260)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label, 1)

        self.meta_label = QLabel("Stage images appear here when a Set Stage block runs.")
        self.meta_label.setObjectName("DrawerMuted")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        self.run_button.clicked.connect(self.run_requested)
        self.stop_button.clicked.connect(self.stop_requested)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def clear_preview(self) -> None:
        self._preview_pixmap = None
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Use Set Stage to preview an image here.")

    def show_stage_payload(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("kind") != "stage_image":
            return

        pixmap = QPixmap()
        if payload.get("path"):
            pixmap.load(str(Path(str(payload["path"])).resolve()))
        elif payload.get("data_base64"):
            pixmap.loadFromData(base64.b64decode(str(payload["data_base64"])))

        if pixmap.isNull():
            return

        self._preview_pixmap = pixmap
        self._apply_preview_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_preview_pixmap()

    def _apply_preview_pixmap(self) -> None:
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        target_width = max(120, self.preview_label.width() - 24)
        target_height = max(120, self.preview_label.height() - 24)
        scaled = self._preview_pixmap.scaled(
            target_width,
            target_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)


class NodeShelf(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("NodeShelf")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("ShelfHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Backpack")
        title.setObjectName("DrawerTitle")
        subtitle = QLabel("Quick access to the blocks already in your project")
        subtitle.setObjectName("DrawerMuted")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle, 1)
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        self.content = QWidget()
        scroll.setWidget(self.content)
        self.cards_layout = QHBoxLayout(self.content)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)

    def set_nodes(self, node_items: list[NodeItem], selected_ids: set[str]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not node_items:
            empty = QLabel("No blocks yet. Drag from the Blocks library to start building.")
            empty.setObjectName("DrawerMuted")
            self.cards_layout.addWidget(empty)
            self.cards_layout.addStretch(1)
            return

        for node_item in node_items:
            card = QFrame()
            card.setObjectName("NodeShelfCard")
            card.setProperty("selected", node_item.model.node_id in selected_ids)
            card.style().unpolish(card)
            card.style().polish(card)

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            card.setFixedWidth(148)

            title = QLabel(node_item.definition.title)
            title.setObjectName("PanelTitle")
            title.setWordWrap(True)
            meta = QLabel(node_item.definition.category.upper())
            meta.setObjectName("DrawerMuted")
            meta.setStyleSheet(f"color: {node_item.definition.color}; font-weight: 700;")
            detail = QLabel(node_item.definition.description)
            detail.setObjectName("DrawerMuted")
            detail.setWordWrap(True)

            card_layout.addWidget(title)
            card_layout.addWidget(meta)
            card_layout.addWidget(detail)
            self.cards_layout.addWidget(card)

        self.cards_layout.addStretch(1)


class NodePalette(QFrame):
    node_requested = Signal(str)

    def __init__(self, catalog: dict[str, NodeDefinition]) -> None:
        super().__init__()
        self.catalog = catalog
        self.active_category = "All"
        self.category_buttons: dict[str, QPushButton] = {}
        self.setObjectName("LibraryPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Blocks")
        title.setObjectName("DrawerTitle")
        layout.addWidget(title)

        subtitle = QLabel("Choose a category, then drag a block into the scripting area or double-click to place it.")
        subtitle.setObjectName("DrawerMuted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search blocks")
        self.search.textChanged.connect(self._rebuild_blocks)
        layout.addWidget(self.search)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        category_rail = QFrame()
        category_rail.setObjectName("CategoryRail")
        category_rail.setFixedWidth(92)
        category_layout = QVBoxLayout(category_rail)
        category_layout.setContentsMargins(8, 8, 8, 8)
        category_layout.setSpacing(6)
        body.addWidget(category_rail)

        button_group = QButtonGroup(self)
        button_group.setExclusive(True)

        all_button = self._create_category_button("All", "#4c97ff")
        all_button.setChecked(True)
        category_layout.addWidget(all_button)
        self.category_buttons["All"] = all_button
        button_group.addButton(all_button)

        for category in CATEGORY_ORDER:
            meta = CATEGORY_META[category]
            button = self._create_category_button(meta["label"], meta["color"])
            category_layout.addWidget(button)
            self.category_buttons[category] = button
            button_group.addButton(button)

        category_layout.addStretch(1)

        blocks_scroll = QScrollArea()
        blocks_scroll.setWidgetResizable(True)
        blocks_scroll.setFrameShape(QFrame.NoFrame)
        body.addWidget(blocks_scroll, 1)

        self.blocks_host = QWidget()
        self.blocks_host.setObjectName("BlockScrollContent")
        blocks_scroll.setWidget(self.blocks_host)

        self.blocks_layout = QVBoxLayout(self.blocks_host)
        self.blocks_layout.setContentsMargins(0, 0, 0, 0)
        self.blocks_layout.setSpacing(10)
        self.blocks_layout.setAlignment(Qt.AlignTop)

        footer = QLabel("Tip: drag blocks in, right-click blocks on the canvas to delete, or drag them back to the library edge.")
        footer.setObjectName("DrawerMuted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._rebuild_blocks()

    def _create_category_button(self, label: str, color: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("CategoryButton")
        button.setCheckable(True)
        button.setFixedHeight(46)
        button.setStyleSheet(
            "QPushButton#CategoryButton {"
            f"border-left: 6px solid {color};"
            "padding-left: 10px;"
            "text-align: left;"
            "}"
        )
        button.clicked.connect(lambda checked=False, name=label: self._select_category(name))
        return button

    def _select_category(self, label: str) -> None:
        self.active_category = label
        self._rebuild_blocks()

    def _rebuild_blocks(self) -> None:
        while self.blocks_layout.count():
            item = self.blocks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        query = self.search.text().strip().lower()

        definitions = [
            definition
            for definition in self.catalog.values()
            if definition.visible_in_palette
            and (self.active_category == "All" or definition.category == self.active_category)
            and (
                not query
                or query in f"{definition.title} {definition.category} {definition.description}".lower()
            )
        ]
        definitions.sort(key=lambda node: (CATEGORY_ORDER.index(node.category) if node.category in CATEGORY_ORDER else 99, node.title))

        if not definitions:
            empty = QLabel("No blocks match that search.")
            empty.setObjectName("DrawerMuted")
            empty.setWordWrap(True)
            self.blocks_layout.addWidget(empty)
            self.blocks_layout.addStretch(1)
            return

        if self.active_category != "All":
            meta = CATEGORY_META.get(self.active_category, {"hint": "Browse blocks"})
            intro = QLabel(meta["hint"])
            intro.setObjectName("DrawerMuted")
            intro.setWordWrap(True)
            self.blocks_layout.addWidget(intro)

        for definition in definitions:
            card = BlockCardButton(definition)
            card.activated.connect(self.node_requested)
            self.blocks_layout.addWidget(card)

        self.blocks_layout.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, project_path: Path | None = None) -> None:
        super().__init__()
        self.catalog = build_node_catalog()
        self.current_project_path: Path | None = None
        self.execution_thread: ExecutionThread | None = None
        self.screen_picker: ScreenPositionPicker | None = None
        self._screen_picker_targets: list[NodeItem] = []
        self.is_dirty = False
        self._loading = False
        self._spawn_count = 0

        self.setWindowTitle("FlowMacro Studio")
        self.resize(1660, 960)
        self.setMinimumSize(1280, 780)
        self.menuBar().setVisible(False)

        self.scene = NodeScene(self.catalog)
        self.view = NodeView(self.scene)
        self.canvas_stage = CanvasStage(self.view)
        self.stage_preview = StagePreview()
        self.palette = NodePalette(self.catalog)
        self.inspector = InspectorPanel()
        self.node_shelf = NodeShelf()
        self.log_output = RuntimeConsole()

        self._build_ui()
        self._wire_events()

        if project_path is not None and project_path.exists():
            self.load_project_from_path(project_path)
        else:
            self.load_starter_project()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppShell")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("ToolBarFrame")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 10, 18, 10)
        toolbar_layout.setSpacing(12)

        brand_strip = QFrame()
        brand_strip.setObjectName("ToolStrip")
        brand_layout = QHBoxLayout(brand_strip)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(12)
        brand_label = QLabel("FlowMacro")
        brand_label.setObjectName("BrandTitle")
        editor_badge = QLabel("Studio")
        editor_badge.setObjectName("BrandBadge")
        self.project_pill = QLabel("Untitled.fmp")
        self.project_pill.setObjectName("ProjectPill")
        brand_layout.addWidget(brand_label)
        brand_layout.addWidget(editor_badge)
        for label in ["File", "Edit", "Tutorials"]:
            nav_button = QPushButton(label)
            nav_button.setObjectName("HeaderNavButton")
            nav_button.setFlat(True)
            brand_layout.addWidget(nav_button)
        brand_layout.addWidget(self.project_pill)
        toolbar_layout.addWidget(brand_strip)
        toolbar_layout.addStretch(1)

        actions_strip = QFrame()
        actions_strip.setObjectName("ToolStrip")
        actions_layout = QHBoxLayout(actions_strip)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        self.new_button = self._make_toolbar_button("New", object_name="HeaderActionButton")
        self.load_button = self._make_toolbar_button("Open", object_name="HeaderActionButton")
        self.save_button = self._make_toolbar_button("Save", object_name="HeaderActionButton")
        self.clear_button = self._make_toolbar_button("Clear", object_name="HeaderActionButton")
        for button in [self.new_button, self.load_button, self.save_button, self.clear_button]:
            actions_layout.addWidget(button)
        toolbar_layout.addWidget(actions_strip)

        root_layout.addWidget(toolbar)

        workspace_row = QWidget()
        workspace_row.setObjectName("WorkspaceRow")
        workspace_layout = QHBoxLayout(workspace_row)
        workspace_layout.setContentsMargins(14, 14, 14, 14)
        workspace_layout.setSpacing(12)

        self.palette.setFixedWidth(324)
        workspace_layout.addWidget(self.palette)
        workspace_layout.addWidget(self.canvas_stage, 1)

        right_column = QWidget()
        right_column.setObjectName("StageColumn")
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_column.setFixedWidth(402)

        right_layout.addWidget(self.stage_preview, 1)

        self.console_frame = QFrame()
        self.console_frame.setObjectName("ConsoleTray")
        console_layout = QVBoxLayout(self.console_frame)
        console_layout.setContentsMargins(12, 10, 12, 12)
        console_layout.setSpacing(10)

        console_header = QFrame()
        console_header.setObjectName("ConsoleHeader")
        console_header_layout = QHBoxLayout(console_header)
        console_header_layout.setContentsMargins(0, 0, 0, 0)
        console_header_layout.setSpacing(8)
        console_title = QLabel("Monitor")
        console_title.setObjectName("ConsoleTitle")
        console_subtitle = QLabel("Messages, file saves, load errors, and runtime output.")
        console_subtitle.setObjectName("DrawerMuted")
        clear_console_button = self._make_toolbar_button("Clear")
        clear_console_button.clicked.connect(self.log_output.clear)
        console_header_layout.addWidget(console_title)
        console_header_layout.addWidget(console_subtitle, 1)
        console_header_layout.addWidget(clear_console_button)
        console_layout.addWidget(console_header)
        console_layout.addWidget(self.log_output, 1)
        workspace_layout.addWidget(right_column)
        root_layout.addWidget(workspace_row, 1)
        root_layout.addWidget(self.console_frame)

        self.setCentralWidget(root)

    def _wire_events(self) -> None:
        self.palette.node_requested.connect(self.add_node_from_palette)
        self.scene.error_message.connect(self.show_error)
        self.scene.project_dirty.connect(self.mark_dirty)
        self.scene.node_selected.connect(self._handle_node_selection)
        self.scene.selection_activated.connect(self._handle_selection_activated)
        self.scene.node_drag_finished.connect(self._handle_node_drag_finished)

        self.new_button.clicked.connect(self.new_project)
        self.load_button.clicked.connect(self.load_project_via_dialog)
        self.save_button.clicked.connect(self.save_project)
        self.clear_button.clicked.connect(self.clear_workspace)
        self.stage_preview.run_requested.connect(self.run_project)
        self.stage_preview.stop_requested.connect(self.stop_project)

    def _make_toolbar_button(self, text: str, object_name: str = "ToolbarButton") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        return button

    def _make_toggle_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ToolbarToggle")
        button.setCheckable(True)
        return button

    def set_library_open(self, is_open: bool, animate: bool = True) -> None:
        _ = is_open, animate

    def set_inspector_open(self, is_open: bool, animate: bool = True) -> None:
        _ = is_open, animate

    def set_console_open(self, is_open: bool, animate: bool = True) -> None:
        _ = is_open, animate

    def _default_project_path(self) -> Path:
        return (Path(__file__).resolve().parent.parent / "default.fmp").resolve()

    def load_starter_project(self) -> None:
        default_project = self._default_project_path()
        if default_project.exists():
            try:
                graph = load_graph(default_project)
            except Exception as exc:  # noqa: BLE001
                self.append_log(f"Default project load failed, using fallback starter: {exc}", reveal=True)
            else:
                self.load_graph(graph, project_path=None)
                self.is_dirty = False
                self._update_window_title()
                self.log_output.clear()
                self.append_log(f"Loaded default project from {default_project.name}.")
                self.append_log("Open the Blocks drawer to add blocks, drag them into the canvas, or press Run.")
                self.stage_preview.clear_preview()
                self.stage_preview.set_status("Ready to run")
                return

        graph = GraphModel(
            nodes=[
                NodeModel("start-node", "start", 80, 120, {}),
                NodeModel("delay-node", "delay", 380, 120, {"duration_ms": 400}),
                NodeModel("set-stage-node", "set_stage", 700, 120, {}),
                NodeModel("pixel-node", "get_pixel_from_image", 1020, 120, {"file_path": "", "x": 320, "y": 180}),
                NodeModel("screenshot-value", "take_screenshot", 620, 330, {}),
            ],
            connections=[
                ConnectionModel("start-node", "next", "delay-node", "flow_in"),
                ConnectionModel("delay-node", "next", "set-stage-node", "flow_in"),
                ConnectionModel("set-stage-node", "next", "pixel-node", "flow_in"),
                ConnectionModel("screenshot-value", "image", "set-stage-node", "image"),
                ConnectionModel("screenshot-value", "image", "pixel-node", "image"),
            ],
        )
        self.load_graph(graph, project_path=None)
        self.is_dirty = False
        self._update_window_title()
        self.log_output.clear()
        self.append_log("Starter project loaded.")
        self.append_log("Open the Blocks drawer to add blocks, drag them into the canvas, or press Run.")
        self.stage_preview.clear_preview()
        self.stage_preview.set_status("Ready to run")
        

    def add_node_from_palette(self, type_id: str) -> None:
        view_center = self.view.mapToScene(self.view.viewport().rect().center())
        offset = QPointF((self._spawn_count % 4) * 28, (self._spawn_count % 4) * 20)
        self._spawn_count += 1
        item = self.scene.create_node(type_id, view_center + offset)
        self.scene.clearSelection()
        item.setSelected(True)
        self.view.setFocus()
        

    def _handle_node_selection(self, node_items) -> None:
        _ = node_items

    def _handle_selection_activated(self, node_items) -> None:
        _ = node_items

    def _handle_node_drag_finished(self, node_item, screen_pos) -> None:
        if not isinstance(node_item, NodeItem):
            return
        snapped = self.scene.snap_released_node(node_item)
        if snapped:
            return
        if not self._is_library_delete_drop(node_item, screen_pos):
            return

        targets = self.scene.selected_node_items() if node_item.isSelected() else [node_item]
        removed = self.scene.remove_nodes(targets)
        if removed:
            count = len(targets)
            label = "blocks" if count != 1 else "block"
            self.append_log(f"Removed {count} {label} by dragging into the Blocks side.", reveal=False)

    def open_screen_picker(self, node_targets) -> None:
        if node_targets is None:
            return
        if isinstance(node_targets, NodeItem):
            targets = [node_targets]
        else:
            targets = [node_item for node_item in node_targets if isinstance(node_item, NodeItem)]
        if not targets:
            return
        if self.screen_picker is not None:
            self.screen_picker.close()
        self._screen_picker_targets = targets
        self.screen_picker = ScreenPositionPicker()
        self.screen_picker.position_picked.connect(self._apply_picked_screen_position)
        self.screen_picker.picker_closed.connect(self._clear_screen_picker)
        self.screen_picker.show()

    def _apply_picked_screen_position(self, x: int, y: int) -> None:
        if not self._screen_picker_targets:
            return
        for node_item in self._screen_picker_targets:
            node_item.model.config["x"] = x
            node_item.model.config["y"] = y
            node_item.refresh_layout()
            node_item.update()
        self.mark_dirty()
        target_label = "blocks" if len(self._screen_picker_targets) > 1 else "block"
        self.append_log(f"[Pick Screen Position] Captured ({x}, {y}) for {len(self._screen_picker_targets)} {target_label}.", reveal=True)

    def _clear_screen_picker(self) -> None:
        self.screen_picker = None
        self._screen_picker_targets = []

    def _is_library_delete_drop(self, node_item: NodeItem, screen_pos: QPoint) -> bool:
        palette_global_rect = QRect(self.palette.mapToGlobal(QPoint(0, 0)), self.palette.size())
        if palette_global_rect.contains(screen_pos):
            return True

        node_center_in_view = self.view.mapFromScene(node_item.sceneBoundingRect().center())
        return node_center_in_view.x() <= 28

    def mark_dirty(self) -> None:
        if self._loading:
            return
        self.is_dirty = True
        self._update_window_title()

    def mark_clean(self) -> None:
        self.is_dirty = False
        self._update_window_title()

    def _update_window_title(self) -> None:
        name = self.current_project_path.name if self.current_project_path else "Untitled.fmp"
        dirty_marker = " *" if self.is_dirty else ""
        self.setWindowTitle(f"FlowMacro Studio - {name}{dirty_marker}")
        pill_text = f"{name}{' - unsaved' if self.is_dirty else ''}"
        self.project_pill.setText(pill_text)

    def show_error(self, message: str) -> None:
        self.canvas_stage.show_error(message)

    def append_log(self, value: object, reveal: bool = False) -> None:
        self.log_output.append_entry(value)
        self.stage_preview.show_stage_payload(value)

    def confirm_discard_changes(self) -> bool:
        if not self.is_dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Changes",
            "This FlowMacro project has unsaved changes. Continue anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def new_project(self) -> None:
        if not self.confirm_discard_changes():
            return
        self.current_project_path = None
        self.load_starter_project()
        self.mark_clean()

    def clear_workspace(self) -> None:
        if not self.scene.node_items and not self.scene.connection_items:
            return
        answer = QMessageBox.question(
            self,
            "Clear Workspace",
            "Remove all blocks and stack links from the current workspace?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.scene.clear_graph()
        self.append_log("Workspace cleared.", reveal=False)
        self.stage_preview.clear_preview()

    def save_project(self) -> None:
        if self.current_project_path is None:
            file_name, _ = QFileDialog.getSaveFileName(
                self,
                "Save FlowMacro Project",
                str((Path.cwd() / "project.fmp").resolve()),
                "FlowMacro Project (*.fmp)",
            )
            if not file_name:
                return
            target = Path(file_name)
            if target.suffix.lower() != ".fmp":
                target = target.with_suffix(".fmp")
            self.current_project_path = target

        try:
            save_graph(self.scene.to_graph(), self.current_project_path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            self.append_log(f"Save failed: {exc}", reveal=True)
            return
        self.mark_clean()
        self.append_log(f"Saved project to {self.current_project_path}", reveal=False)

    def load_project_via_dialog(self) -> None:
        if not self.confirm_discard_changes():
            return
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open FlowMacro Project",
            str(Path.cwd().resolve()),
            "FlowMacro Project (*.fmp)",
        )
        if file_name:
            self.load_project_from_path(Path(file_name))

    def load_project_from_path(self, project_path: Path) -> None:
        if not project_path.exists():
            self.show_error(f"Could not find {project_path}")
            return
        try:
            graph = load_graph(project_path)
        except Exception as exc:  # noqa: BLE001
            self.show_error(str(exc))
            self.append_log(f"Load failed: {exc}", reveal=True)
            return
        self.load_graph(graph, project_path)
        self.append_log(f"Loaded project from {project_path}", reveal=False)

    def load_graph(self, graph: GraphModel, project_path: Path | None) -> None:
        self._loading = True
        try:
            self.scene.load_graph(graph)
            self.current_project_path = project_path
            self.mark_clean()
        finally:
            self._loading = False
        self._update_window_title()
        self.stage_preview.clear_preview()
        QTimer.singleShot(0, self.view.fit_content)

    def run_project(self) -> None:
        if self.execution_thread is not None and self.execution_thread.isRunning():
            return
        self.append_log("Running FlowMacro project...", reveal=True)
        self.stage_preview.set_status("Running macro...")
        self.execution_thread = ExecutionThread(
            graph=self.scene.to_graph(),
            catalog=self.catalog,
            project_path=self.current_project_path,
        )
        self.execution_thread.log_message.connect(self._handle_runtime_log)
        self.execution_thread.run_failed.connect(self._handle_run_failed)
        self.execution_thread.run_succeeded.connect(self._handle_run_succeeded)
        self.execution_thread.finished.connect(self._handle_run_finished)
        self.stage_preview.run_button.setEnabled(False)
        self.stage_preview.stop_button.setEnabled(True)
        self.execution_thread.start()

    def stop_project(self) -> None:
        if self.execution_thread is not None:
            self.execution_thread.stop()
            self.append_log("Stop requested...", reveal=True)
            self.stage_preview.set_status("Stopping...")

    def _handle_runtime_log(self, message: object) -> None:
        self.append_log(message, reveal=True)

    def _handle_run_failed(self, message: str) -> None:
        self.show_error(message)
        self.append_log(f"Run failed: {message}", reveal=True)
        self.stage_preview.set_status("Run failed")

    def _handle_run_succeeded(self) -> None:
        self.append_log("Run completed successfully.", reveal=True)
        self.stage_preview.set_status("Run completed")

    def _handle_run_finished(self) -> None:
        self.stage_preview.run_button.setEnabled(True)
        self.stage_preview.stop_button.setEnabled(False)
        _release_all_held_inputs()

    def _refresh_node_shelf(self) -> None:
        return

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.screen_picker is not None:
            self.screen_picker.close()
        if self.execution_thread is not None and self.execution_thread.isRunning():
            self.execution_thread.stop()
            self.execution_thread.wait(1000)
        _release_all_held_inputs()
        if not self.confirm_discard_changes():
            event.ignore()
            return
        super().closeEvent(event)


def create_application() -> QApplication:
    app = QApplication.instance()
    if app is not None:
        return app

    app = QApplication([])
    app.setApplicationName("FlowMacro Studio")
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 9))
    app.setStyleSheet(WINDOW_STYLESHEET)

    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#eef3fb"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f6f9ff"))
    palette.setColor(QPalette.Text, QColor("#304260"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#304260"))
    palette.setColor(QPalette.Highlight, QColor("#4c97ff"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    return app
