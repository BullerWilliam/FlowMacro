from __future__ import annotations

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
from PySide6.QtGui import QCloseEvent, QColor, QDrag, QGuiApplication, QPainter, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .canvas import NODE_MIME_TYPE, NodeScene, NodeView
from .inspector import InspectorPanel
from .models import ConnectionModel, GraphModel, NodeDefinition, NodeModel
from .node_definitions import build_node_catalog
from .runtime import GraphRuntime
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

        if isinstance(value, dict) and value.get("kind") == "image" and value.get("path"):
            image_path = Path(str(value["path"])).resolve()
            image_uri = QUrl.fromLocalFile(str(image_path)).toString()
            cursor.insertHtml('<span style="color:#8fb5eb;">[Print] Image</span><br>')
            cursor.insertHtml(f'<img src="{image_uri}" width="340" /><br>')
            cursor.insertHtml(
                f'<span style="color:#a8c9f7;font-family:Consolas;">{escape(str(image_path))}</span>'
            )
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
        self._cursor_pos = QCursor.pos() if "QCursor" in globals() else QPoint(0, 0)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        self.error_toast = QLabel(self)
        self.error_toast.setObjectName("OverlayError")
        self.error_toast.setWordWrap(True)
        self.error_toast.hide()

        self.controls = QFrame(self)
        self.controls.setObjectName("CanvasControls")
        controls_layout = QHBoxLayout(self.controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(6)

        self.zoom_out_button = self._create_canvas_button("-", "Zoom out")
        self.zoom_in_button = self._create_canvas_button("+", "Zoom in")
        self.reset_zoom_button = self._create_canvas_button("100%", "Reset zoom")
        self.fit_view_button = self._create_canvas_button("Fit", "Fit all nodes")

        controls_layout.addWidget(self.zoom_out_button)
        controls_layout.addWidget(self.zoom_in_button)
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
        self.controls.move(self.width() - self.controls.width() - controls_margin, controls_margin)
        self.controls.raise_()

        if self.error_toast.isHidden():
            return

        toast_width = min(520, max(260, self.width() - 40))
        self.error_toast.setFixedWidth(toast_width)
        self.error_toast.adjustSize()
        self.error_toast.move((self.width() - self.error_toast.width()) // 2, 16)


class NodePaletteTree(QTreeWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.CopyAction)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        node_type = item.data(0, Qt.UserRole)
        if not node_type:
            return
        mime_data = QMimeData()
        mime_data.setData(NODE_MIME_TYPE, str(node_type).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.CopyAction)


class NodePalette(QFrame):
    node_requested = Signal(str)

    def __init__(self, catalog: dict[str, NodeDefinition]) -> None:
        super().__init__()
        self.catalog = catalog
        self.setObjectName("LibraryPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Node Library")
        title.setObjectName("DrawerTitle")
        layout.addWidget(title)

        subtitle = QLabel("Drag blocks into the workspace or double-click to place them in the center.")
        subtitle.setObjectName("DrawerMuted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search actions, logic, strings, files...")
        self.search.textChanged.connect(self._rebuild_tree)
        layout.addWidget(self.search)

        self.tree = NodePaletteTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._handle_item_request)
        self.tree.itemActivated.connect(self._handle_item_request)
        layout.addWidget(self.tree, 1)

        footer = QLabel("Tip: press Delete on selected nodes or connections to remove them.")
        footer.setObjectName("DrawerMuted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        query = self.search.text().strip().lower()
        self.tree.clear()

        grouped: dict[str, list[NodeDefinition]] = {}
        for definition in self.catalog.values():
            if not definition.visible_in_palette:
                continue
            haystack = f"{definition.title} {definition.category} {definition.description}".lower()
            if query and query not in haystack:
                continue
            grouped.setdefault(definition.category, []).append(definition)

        for category in sorted(grouped):
            parent = QTreeWidgetItem([category.upper()])
            parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(parent)
            for definition in sorted(grouped[category], key=lambda node: node.title):
                item = QTreeWidgetItem([definition.title])
                item.setData(0, Qt.UserRole, definition.type_id)
                item.setToolTip(0, definition.description)
                parent.addChild(item)
            parent.setExpanded(True)

    def _handle_item_request(self, item: QTreeWidgetItem, column: int) -> None:
        node_type = item.data(0, Qt.UserRole)
        if node_type:
            self.node_requested.emit(str(node_type))


class MainWindow(QMainWindow):
    def __init__(self, project_path: Path | None = None) -> None:
        super().__init__()
        self.catalog = build_node_catalog()
        self.current_project_path: Path | None = None
        self.execution_thread: ExecutionThread | None = None
        self.screen_picker: ScreenPositionPicker | None = None
        self._screen_picker_node = None
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
        self.palette = NodePalette(self.catalog)
        self.inspector = InspectorPanel()
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
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(10)

        brand_strip = QFrame()
        brand_strip.setObjectName("ToolStrip")
        brand_layout = QHBoxLayout(brand_strip)
        brand_layout.setContentsMargins(12, 8, 12, 8)
        brand_layout.setSpacing(10)
        brand_label = QLabel("FlowMacro Studio")
        brand_label.setObjectName("BrandTitle")
        self.project_pill = QLabel("Untitled.fmp")
        self.project_pill.setObjectName("ProjectPill")
        brand_layout.addWidget(brand_label)
        brand_layout.addWidget(self.project_pill)
        toolbar_layout.addWidget(brand_strip)
        toolbar_layout.addStretch(1)

        actions_strip = QFrame()
        actions_strip.setObjectName("ToolStrip")
        actions_layout = QHBoxLayout(actions_strip)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(6)
        self.new_button = self._make_toolbar_button("New")
        self.load_button = self._make_toolbar_button("Open")
        self.save_button = self._make_toolbar_button("Save")
        self.run_button = self._make_toolbar_button("Run", object_name="PrimaryButton")
        self.stop_button = self._make_toolbar_button("Stop", object_name="DangerButton")
        self.stop_button.setEnabled(False)
        for button in [self.new_button, self.load_button, self.save_button, self.run_button, self.stop_button]:
            actions_layout.addWidget(button)
        toolbar_layout.addWidget(actions_strip)

        toggles_strip = QFrame()
        toggles_strip.setObjectName("ToolStrip")
        toggles_layout = QHBoxLayout(toggles_strip)
        toggles_layout.setContentsMargins(8, 8, 8, 8)
        toggles_layout.setSpacing(6)
        self.library_toggle = self._make_toggle_button("Library")
        self.inspector_toggle = self._make_toggle_button("Inspector")
        self.console_toggle = self._make_toggle_button("Console")
        for button in [self.library_toggle, self.inspector_toggle, self.console_toggle]:
            toggles_layout.addWidget(button)
        toolbar_layout.addWidget(toggles_strip)

        root_layout.addWidget(toolbar)

        workspace_row = QWidget()
        workspace_layout = QHBoxLayout(workspace_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self.library_dock = AnimatedDock("width", 300)
        self.library_dock.body_layout.addWidget(self.palette)
        workspace_layout.addWidget(self.library_dock)

        workspace_layout.addWidget(self.canvas_stage, 1)

        self.inspector_dock = AnimatedDock("width", 340)
        self.inspector_dock.body_layout.addWidget(self.inspector)
        workspace_layout.addWidget(self.inspector_dock)

        root_layout.addWidget(workspace_row, 1)

        self.console_dock = AnimatedDock("height", 220)
        console_frame = QFrame()
        console_frame.setObjectName("ConsoleTray")
        console_layout = QVBoxLayout(console_frame)
        console_layout.setContentsMargins(12, 10, 12, 12)
        console_layout.setSpacing(10)

        console_header = QFrame()
        console_header.setObjectName("ConsoleHeader")
        console_header_layout = QHBoxLayout(console_header)
        console_header_layout.setContentsMargins(0, 0, 0, 0)
        console_header_layout.setSpacing(8)
        console_title = QLabel("Runtime Console")
        console_title.setObjectName("ConsoleTitle")
        console_subtitle = QLabel("Print output, file saves, load errors, and runtime messages.")
        console_subtitle.setObjectName("DrawerMuted")
        clear_console_button = self._make_toolbar_button("Clear")
        clear_console_button.clicked.connect(self.log_output.clear)
        console_header_layout.addWidget(console_title)
        console_header_layout.addWidget(console_subtitle, 1)
        console_header_layout.addWidget(clear_console_button)
        console_layout.addWidget(console_header)
        console_layout.addWidget(self.log_output, 1)

        self.console_dock.body_layout.addWidget(console_frame)
        root_layout.addWidget(self.console_dock)

        self.setCentralWidget(root)

    def _wire_events(self) -> None:
        self.palette.node_requested.connect(self.add_node_from_palette)
        self.inspector.config_changed.connect(self.mark_dirty)
        self.inspector.pick_screen_position_requested.connect(self.open_screen_picker)
        self.scene.error_message.connect(self.show_error)
        self.scene.project_dirty.connect(self.mark_dirty)
        self.scene.node_selected.connect(self._handle_node_selection)

        self.new_button.clicked.connect(self.new_project)
        self.load_button.clicked.connect(self.load_project_via_dialog)
        self.save_button.clicked.connect(self.save_project)
        self.run_button.clicked.connect(self.run_project)
        self.stop_button.clicked.connect(self.stop_project)

        self.library_toggle.clicked.connect(self.set_library_open)
        self.inspector_toggle.clicked.connect(self.set_inspector_open)
        self.console_toggle.clicked.connect(self.set_console_open)

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
        self.library_toggle.setChecked(is_open)
        self.library_dock.set_open(is_open, animate=animate)

    def set_inspector_open(self, is_open: bool, animate: bool = True) -> None:
        self.inspector_toggle.setChecked(is_open)
        self.inspector_dock.set_open(is_open, animate=animate)

    def set_console_open(self, is_open: bool, animate: bool = True) -> None:
        self.console_toggle.setChecked(is_open)
        self.console_dock.set_open(is_open, animate=animate)

    def load_starter_project(self) -> None:
        capture_template = str(Path.cwd().resolve() / "captures" / "capture_{timestamp}.png")
        graph = GraphModel(
            nodes=[
                NodeModel("start-node", "start", 80, 120, {}),
                NodeModel("delay-node", "delay", 380, 120, {"duration_ms": 400}),
                NodeModel("screen-node", "take_screenshot", 700, 120, {"file_path": capture_template}),
                NodeModel("pixel-node", "get_pixel", 1040, 120, {"x": 320, "y": 180}),
                NodeModel("duration-value", "number_value", 340, 340, {"value": 400}),
                NodeModel("file-path-value", "text_value", 660, 340, {"value": capture_template}),
                NodeModel("x-value", "number_value", 980, 340, {"value": 320}),
                NodeModel("y-value", "number_value", 1130, 340, {"value": 180}),
            ],
            connections=[
                ConnectionModel("start-node", "next", "delay-node", "flow_in"),
                ConnectionModel("delay-node", "next", "screen-node", "flow_in"),
                ConnectionModel("screen-node", "next", "pixel-node", "flow_in"),
                ConnectionModel("duration-value", "value", "delay-node", "duration_ms"),
                ConnectionModel("file-path-value", "value", "screen-node", "file_path"),
                ConnectionModel("x-value", "value", "pixel-node", "x"),
                ConnectionModel("y-value", "value", "pixel-node", "y"),
            ],
        )
        self.load_graph(graph, project_path=None)
        self.is_dirty = False
        self._update_window_title()
        self.log_output.clear()
        self.append_log("Starter project loaded.")
        self.append_log("Open the Library drawer to add new blocks, drag blocks out into the canvas, or press Run.")
        self.set_library_open(False, animate=False)
        self.set_inspector_open(False, animate=False)
        self.set_console_open(False, animate=False)

    def add_node_from_palette(self, type_id: str) -> None:
        view_center = self.view.mapToScene(self.view.viewport().rect().center())
        offset = QPointF((self._spawn_count % 4) * 28, (self._spawn_count % 4) * 20)
        self._spawn_count += 1
        item = self.scene.create_node(type_id, view_center + offset)
        self.scene.clearSelection()
        item.setSelected(True)
        self.view.setFocus()

    def _handle_node_selection(self, node_item) -> None:
        self.inspector.set_node(node_item)
        if node_item is None:
            self.set_inspector_open(False)
            return
        self.set_inspector_open(True)

    def open_screen_picker(self, node_item) -> None:
        if node_item is None:
            return
        if self.screen_picker is not None:
            self.screen_picker.close()
        self._screen_picker_node = node_item
        self.screen_picker = ScreenPositionPicker()
        self.screen_picker.position_picked.connect(self._apply_picked_screen_position)
        self.screen_picker.picker_closed.connect(self._clear_screen_picker)
        self.screen_picker.show()

    def _apply_picked_screen_position(self, x: int, y: int) -> None:
        node_item = self._screen_picker_node
        if node_item is None:
            return
        node_item.model.config["x"] = x
        node_item.model.config["y"] = y
        node_item.refresh_layout()
        node_item.update()
        self.inspector.set_node(node_item)
        self.mark_dirty()
        self.append_log(f"[Pick Screen Position] Captured ({x}, {y}).", reveal=True)

    def _clear_screen_picker(self) -> None:
        self.screen_picker = None
        self._screen_picker_node = None

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
        if reveal:
            self.set_console_open(True)
        self.log_output.append_entry(value)

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
        self.inspector.set_node(None)
        self.set_inspector_open(False, animate=False)
        self._update_window_title()
        QTimer.singleShot(0, self.view.fit_content)

    def run_project(self) -> None:
        if self.execution_thread is not None and self.execution_thread.isRunning():
            return
        self.append_log("Running FlowMacro project...", reveal=True)
        self.execution_thread = ExecutionThread(
            graph=self.scene.to_graph(),
            catalog=self.catalog,
            project_path=self.current_project_path,
        )
        self.execution_thread.log_message.connect(self._handle_runtime_log)
        self.execution_thread.run_failed.connect(self._handle_run_failed)
        self.execution_thread.run_succeeded.connect(self._handle_run_succeeded)
        self.execution_thread.finished.connect(self._handle_run_finished)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.execution_thread.start()

    def stop_project(self) -> None:
        if self.execution_thread is not None:
            self.execution_thread.stop()
            self.append_log("Stop requested...", reveal=True)

    def _handle_runtime_log(self, message: object) -> None:
        self.append_log(message, reveal=True)

    def _handle_run_failed(self, message: str) -> None:
        self.show_error(message)
        self.append_log(f"Run failed: {message}", reveal=True)

    def _handle_run_succeeded(self) -> None:
        self.append_log("Run completed successfully.", reveal=True)

    def _handle_run_finished(self) -> None:
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.screen_picker is not None:
            self.screen_picker.close()
        if self.execution_thread is not None and self.execution_thread.isRunning():
            self.execution_thread.stop()
            self.execution_thread.wait(1000)
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
    app.setStyleSheet(WINDOW_STYLESHEET)

    palette = app.palette()
    palette.setColor(QPalette.Window, QColor("#08111c"))
    palette.setColor(QPalette.Base, QColor("#08111c"))
    palette.setColor(QPalette.AlternateBase, QColor("#0b1625"))
    palette.setColor(QPalette.Text, QColor("#dce8ff"))
    palette.setColor(QPalette.Button, QColor("#12233c"))
    palette.setColor(QPalette.ButtonText, QColor("#edf5ff"))
    palette.setColor(QPalette.Highlight, QColor("#2f78d7"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    return app
