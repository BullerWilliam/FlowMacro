from __future__ import annotations

import uuid
from typing import Iterable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
)

from .models import ConnectionModel, GraphModel, NodeDefinition, NodeModel, PortDefinition
from .styles import port_color, with_alpha

NODE_MIME_TYPE = "application/x-flowmacro-node"


class PortItem(QGraphicsObject):
    radius = 5.1

    def __init__(self, node_item: "NodeItem", definition: PortDefinition) -> None:
        super().__init__(node_item)
        self.node_item = node_item
        self.definition = definition
        self.connections: list[ConnectionItem] = []
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        base_color = port_color(self.definition.type_name)
        glow_color = with_alpha(base_color, 95 if self._hovered else 42)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setPen(Qt.NoPen)
        painter.setBrush(glow_color)
        painter.drawEllipse(QPointF(0, 0), self.radius + 2.8, self.radius + 2.8)

        painter.setPen(QPen(QColor("#ffffff"), 1.2))
        painter.setBrush(base_color)
        painter.drawEllipse(QPointF(0, 0), self.radius, self.radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(with_alpha(QColor("#ffffff"), 95))
        painter.drawEllipse(QPointF(-1.2, -1.2), self.radius * 0.38, self.radius * 0.38)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if isinstance(scene, NodeScene):
                scene.begin_connection(self)
                self.grabMouse()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        scene = self.scene()
        if isinstance(scene, NodeScene) and scene.is_connecting_from(self):
            scene.update_preview(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        if isinstance(scene, NodeScene) and scene.is_connecting_from(self):
            self.ungrabMouse()
            target = scene.port_at(event.scenePos(), exclude=self)
            scene.finish_connection(target)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class ConnectionItem(QGraphicsPathItem):
    def __init__(
        self,
        source_port: PortItem,
        target_port: PortItem | None = None,
        preview: bool = False,
    ) -> None:
        super().__init__()
        self.source_port = source_port
        self.target_port = target_port
        self.preview = preview
        self.end_pos = source_port.scene_center()
        self._hovered = False
        self.setFlag(QGraphicsItem.ItemIsSelectable, not preview)
        self.setAcceptHoverEvents(not preview)
        self.setCursor(Qt.PointingHandCursor if not preview else Qt.ArrowCursor)
        self.setZValue(-2 if not preview else 0)
        self.update_path()

    def update_path(self, end_pos: QPointF | None = None) -> None:
        start = self.source_port.scene_center()
        end = self.target_port.scene_center() if self.target_port else (end_pos or self.end_pos)
        self.end_pos = end

        horizontal_distance = abs(end.x() - start.x())
        distance = max(68.0, min(180.0, horizontal_distance * 0.55))
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(start.x() + distance, start.y()),
            QPointF(end.x() - distance, end.y()),
            end,
        )
        self.setPath(path)
        self.update()

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-10, -10, 10, 10)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = port_color(self.source_port.definition.type_name)
        path = self.path()

        if self.preview:
            glow_width = 6.0
            core_width = 2.0
            glow_alpha = 70
            core_color = with_alpha(color, 225)
        else:
            active = self.isSelected() or self._hovered
            glow_width = 8.0 if active else 6.2
            core_width = 2.8 if active else 2.2
            glow_alpha = 120 if active else 62
            core_color = color.darker(105) if active else color

        glow_pen = QPen(with_alpha(color, glow_alpha), glow_width)
        glow_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        painter.setPen(QPen(with_alpha(QColor("#ffffff"), 190), core_width + 1.2))
        painter.drawPath(path)

        core_pen = QPen(core_color, core_width)
        core_pen.setCapStyle(Qt.RoundCap)
        if self.preview:
            core_pen.setStyle(Qt.DashLine)
        painter.setPen(core_pen)
        painter.drawPath(path)

        if self.isSelected() and not self.preview:
            highlight_pen = QPen(with_alpha(QColor("#ffffff"), 95), 0.9)
            highlight_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(highlight_pen)
            painter.drawPath(path)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def detach(self) -> None:
        if self in self.source_port.connections:
            self.source_port.connections.remove(self)
        if self.target_port and self in self.target_port.connections:
            self.target_port.connections.remove(self)


class NodeItem(QGraphicsObject):
    width = 248.0

    def __init__(self, model: NodeModel, definition: NodeDefinition) -> None:
        super().__init__()
        self.model = model
        self.definition = definition
        self.inputs: dict[str, PortItem] = {}
        self.outputs: dict[str, PortItem] = {}
        self.height = 120.0
        self._hovered = False
        self._press_scene_pos: QPointF | None = None
        self._drag_started = False
        self.setAcceptHoverEvents(True)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsScenePositionChanges
        )
        self.setZValue(1)
        self._build_ports()
        self.refresh_layout()
        self.setPos(self.model.x, self.model.y)

    def _build_ports(self) -> None:
        for port in self.definition.inputs:
            self.inputs[port.key] = PortItem(self, port)
        for port in self.definition.outputs:
            self.outputs[port.key] = PortItem(self, port)

    def all_ports(self) -> Iterable[PortItem]:
        return [*self.inputs.values(), *self.outputs.values()]

    def refresh_layout(self) -> None:
        port_top = 58.0
        spacing = 26.0
        summary_lines = self.summary_lines()
        summary_height = max(30.0, 16.0 * len(summary_lines) + 14.0)
        self.height = max(
            124.0,
            port_top + max(len(self.inputs), len(self.outputs), 1) * spacing + summary_height + 8.0,
        )
        self.prepareGeometryChange()
        for index, port in enumerate(self.definition.inputs):
            self.inputs[port.key].setPos(0.0, port_top + index * spacing)
        for index, port in enumerate(self.definition.outputs):
            self.outputs[port.key].setPos(self.width, port_top + index * spacing)
        self.update()

    def summary_lines(self) -> list[str]:
        def shrink(value: object) -> str:
            text = str(value)
            return text if len(text) <= 26 else f"{text[:23]}..."

        if not self.definition.config_fields:
            summary = self.definition.description
            return [summary if len(summary) <= 34 else f"{summary[:31]}..."]

        lines: list[str] = []
        for field in self.definition.config_fields[:2]:
            value = self.model.config.get(field.key, field.default)
            if isinstance(value, bool):
                value = "True" if value else "False"
            lines.append(f"{field.label}: {shrink(value)}")
        return lines

    def boundingRect(self) -> QRectF:
        return QRectF(-14, -14, self.width + 28, self.height + 28)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = QRectF(0, 0, self.width, self.height)
        painter.setRenderHint(QPainter.Antialiasing, True)

        accent = QColor(self.definition.color)
        outline_color = accent.darker(110) if self.isSelected() else QColor("#d7e1f2")
        if self._hovered and not self.isSelected():
            outline_color = accent.lighter(118)

        shadow_rect = rect.adjusted(3, 6, 3, 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(112, 146, 198, 38))
        painter.drawRoundedRect(shadow_rect, 14, 14)

        if self.isSelected():
            painter.setBrush(with_alpha(accent, 35))
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 16, 16)

        painter.setPen(QPen(outline_color, 1.4))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 13, 13)

        accent_strip = QRectF(0, 0, self.width, 40)
        accent_gradient = QLinearGradient(accent_strip.topLeft(), accent_strip.topRight())
        accent_gradient.setColorAt(0.0, accent.lighter(112))
        accent_gradient.setColorAt(1.0, accent.darker(108))
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent_gradient)
        painter.drawRoundedRect(accent_strip, 13, 13)
        painter.drawRect(0, 18, self.width, 22)

        painter.setPen(QColor("#ffffff"))
        title_font = painter.font()
        title_font.setPointSize(10.5)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(QRectF(14, 10, self.width - 96, 22), self.definition.title)

        chip_text = self.definition.category.upper()
        chip_rect = QRectF(self.width - 82, 10, 68, 20)
        painter.setPen(QPen(with_alpha(QColor("#ffffff"), 165), 1))
        painter.setBrush(with_alpha(QColor("#ffffff"), 40))
        painter.drawRoundedRect(chip_rect, 8, 8)
        chip_font = painter.font()
        chip_font.setPointSize(7)
        chip_font.setBold(True)
        painter.setFont(chip_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(chip_rect, Qt.AlignCenter, chip_text)

        port_name_font = painter.font()
        port_name_font.setPointSize(8.3)
        port_name_font.setBold(True)
        type_font = painter.font()
        type_font.setPointSize(7)
        type_font.setBold(False)

        for port in self.definition.inputs:
            item = self.inputs[port.key]
            port_y = item.y()
            wire_color = port_color(port.type_name)
            painter.setPen(QPen(with_alpha(wire_color, 180), 1.2))
            painter.drawLine(0, port_y, 14, port_y)
            painter.setFont(port_name_font)
            painter.setPen(QColor("#2d4164"))
            painter.drawText(QRectF(16, port_y - 9, 118, 13), port.label)
            if port.type_name != "flow":
                painter.setFont(type_font)
                painter.setPen(with_alpha(wire_color, 220))
                painter.drawText(QRectF(16, port_y + 4, 80, 12), port.type_name)

        for port in self.definition.outputs:
            item = self.outputs[port.key]
            port_y = item.y()
            wire_color = port_color(port.type_name)
            painter.setPen(QPen(with_alpha(wire_color, 180), 1.2))
            painter.drawLine(self.width - 14, port_y, self.width, port_y)
            painter.setFont(port_name_font)
            painter.setPen(QColor("#2d4164"))
            painter.drawText(
                QRectF(self.width - 134, port_y - 9, 118, 13),
                Qt.AlignRight,
                port.label,
            )
            if port.type_name != "flow":
                painter.setFont(type_font)
                painter.setPen(with_alpha(wire_color, 220))
                painter.drawText(
                    QRectF(self.width - 98, port_y + 4, 82, 12),
                    Qt.AlignRight,
                    port.type_name,
                )

        lines = self.summary_lines()
        summary_height = max(30.0, 16.0 * len(lines) + 14.0)
        summary_top = self.height - summary_height - 10.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(with_alpha(accent, 22))
        painter.drawRoundedRect(QRectF(10, summary_top - 6, self.width - 20, summary_height + 8), 12, 12)

        painter.setFont(type_font)
        painter.setPen(QColor("#5d7398"))
        painter.drawText(QRectF(14, summary_top, 64, 12), "STATUS")

        painter.setPen(QColor("#3e5479"))
        for index, line in enumerate(lines):
            painter.drawText(
                QRectF(14, summary_top + 12 + index * 14.0, self.width - 28, 13),
                line,
            )

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_scene_pos = event.scenePos()
            self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton and self._press_scene_pos is not None:
            if not self._drag_started:
                distance = (event.scenePos() - self._press_scene_pos).manhattanLength()
                if distance < QApplication.startDragDistance():
                    event.accept()
                    return
                self._drag_started = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_drag_started = self._drag_started
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if isinstance(scene, NodeScene) and event.button() == Qt.LeftButton:
            if was_drag_started:
                scene.node_drag_finished.emit(self, event.screenPos())
            elif self.isSelected():
                scene.selection_activated.emit(scene.selected_node_items())
        self._press_scene_pos = None
        self._drag_started = False

    def contextMenuEvent(self, event) -> None:
        scene = self.scene()
        if not isinstance(scene, NodeScene):
            super().contextMenuEvent(event)
            return

        if not self.isSelected():
            scene.clearSelection()
            self.setSelected(True)

        selected_nodes = scene.selected_node_items()
        delete_label = "Delete Selected" if len(selected_nodes) > 1 else "Delete"

        menu = QMenu()
        delete_action = menu.addAction(delete_label)
        chosen_action = menu.exec(event.screenPos())
        if chosen_action is delete_action:
            scene.delete_selected()
            event.accept()
            return
        super().contextMenuEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.model.x = float(self.pos().x())
            self.model.y = float(self.pos().y())
            for port in self.all_ports():
                for connection in list(port.connections):
                    connection.update_path()
            scene = self.scene()
            if isinstance(scene, NodeScene):
                scene.project_dirty.emit()
        return super().itemChange(change, value)


class NodeScene(QGraphicsScene):
    error_message = Signal(str)
    project_dirty = Signal()
    node_selected = Signal(object)
    selection_activated = Signal(object)
    node_drag_finished = Signal(object, object)

    def __init__(self, catalog: dict[str, NodeDefinition]) -> None:
        super().__init__()
        self.catalog = catalog
        self.node_items: dict[str, NodeItem] = {}
        self.connection_items: list[ConnectionItem] = []
        self.drag_source: PortItem | None = None
        self.preview_connection: ConnectionItem | None = None
        self.setSceneRect(-6000, -6000, 12000, 12000)
        self.selectionChanged.connect(self._emit_selected_node)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(rect, QColor("#f7f9fe"))
        dot_pen = QPen(QColor("#dde6f4"))
        dot_pen.setWidth(1)
        painter.setPen(dot_pen)
        grid_size = 24
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        for x in range(left, int(rect.right()) + grid_size, grid_size):
            for y in range(top, int(rect.bottom()) + grid_size, grid_size):
                painter.drawPoint(x, y)

    def clear_graph(self) -> None:
        self.drag_source = None
        self.preview_connection = None
        self.node_items.clear()
        self.connection_items.clear()
        self.clear()
        self.project_dirty.emit()

    def load_graph(self, graph: GraphModel) -> None:
        self.clear()
        self.drag_source = None
        self.preview_connection = None
        self.node_items.clear()
        self.connection_items.clear()

        for node in graph.nodes:
            definition = self.catalog.get(node.type_id)
            if not definition:
                continue
            self._add_node_item(NodeItem(node, definition))

        for connection in graph.connections:
            self._add_connection_from_model(connection, emit_dirty=False)

        self._emit_selected_node()

    def to_graph(self) -> GraphModel:
        nodes = [
            NodeModel(
                node_id=node_item.model.node_id,
                type_id=node_item.model.type_id,
                x=node_item.pos().x(),
                y=node_item.pos().y(),
                config=dict(node_item.model.config),
            )
            for node_item in self.node_items.values()
        ]
        connections = [
            ConnectionModel(
                from_node_id=connection.source_port.node_item.model.node_id,
                from_port_key=connection.source_port.definition.key,
                to_node_id=connection.target_port.node_item.model.node_id,
                to_port_key=connection.target_port.definition.key,
            )
            for connection in self.connection_items
            if connection.target_port is not None
        ]
        return GraphModel(nodes=nodes, connections=connections)

    def create_node(self, type_id: str, position: QPointF) -> NodeItem:
        definition = self.catalog[type_id]
        node = NodeModel(
            node_id=uuid.uuid4().hex,
            type_id=type_id,
            x=position.x(),
            y=position.y(),
            config=definition.default_config(),
        )
        item = NodeItem(node, definition)
        self._add_node_item(item)
        self.project_dirty.emit()
        return item

    def _add_node_item(self, item: NodeItem) -> None:
        self.node_items[item.model.node_id] = item
        self.addItem(item)

    def begin_connection(self, source_port: PortItem) -> None:
        self.cancel_preview()
        self.drag_source = source_port
        self.preview_connection = ConnectionItem(source_port, preview=True)
        self.addItem(self.preview_connection)

    def is_connecting_from(self, port: PortItem) -> bool:
        return self.drag_source is port and self.preview_connection is not None

    def update_preview(self, scene_pos: QPointF) -> None:
        if self.preview_connection:
            self.preview_connection.update_path(scene_pos)

    def cancel_preview(self) -> None:
        if self.preview_connection:
            self.removeItem(self.preview_connection)
            self.preview_connection = None
        self.drag_source = None

    def finish_connection(self, target_port: PortItem | None) -> None:
        source_port = self.drag_source
        self.cancel_preview()

        if source_port is None or target_port is None:
            return

        normalized = self._normalize_ports(source_port, target_port)
        if normalized is None:
            return

        output_port, input_port = normalized

        existing = self._incoming_connection_for(input_port)
        if existing is not None:
            self.remove_connection(existing, emit_dirty=False)

        duplicate = next(
            (
                connection
                for connection in self.connection_items
                if connection.source_port is output_port and connection.target_port is input_port
            ),
            None,
        )
        if duplicate is not None:
            return

        model = ConnectionModel(
            from_node_id=output_port.node_item.model.node_id,
            from_port_key=output_port.definition.key,
            to_node_id=input_port.node_item.model.node_id,
            to_port_key=input_port.definition.key,
        )
        self._add_connection_from_model(model, emit_dirty=True)

    def _normalize_ports(self, first: PortItem, second: PortItem) -> tuple[PortItem, PortItem] | None:
        if first.definition.is_output == second.definition.is_output:
            self.error_message.emit("Connect an output port to an input port.")
            return None

        output_port = first if first.definition.is_output else second
        input_port = second if first.definition.is_output else first

        if output_port.node_item is input_port.node_item:
            self.error_message.emit("Connections between ports on the same node are disabled.")
            return None

        type_match = output_port.definition.type_name == input_port.definition.type_name
        accepts_any = "any" in {output_port.definition.type_name, input_port.definition.type_name}
        if not type_match and not accepts_any:
            self.error_message.emit(
                f"Wrong type: '{output_port.definition.type_name}' cannot connect to '{input_port.definition.type_name}'."
            )
            return None

        return output_port, input_port

    def _incoming_connection_for(self, input_port: PortItem) -> ConnectionItem | None:
        return next((connection for connection in input_port.connections if connection.target_port is input_port), None)

    def _add_connection_from_model(self, model: ConnectionModel, emit_dirty: bool) -> None:
        source_node = self.node_items.get(model.from_node_id)
        target_node = self.node_items.get(model.to_node_id)
        if source_node is None or target_node is None:
            return

        source_port = source_node.outputs.get(model.from_port_key)
        target_port = target_node.inputs.get(model.to_port_key)
        if source_port is None or target_port is None:
            return

        connection = ConnectionItem(source_port, target_port=target_port)
        source_port.connections.append(connection)
        target_port.connections.append(connection)
        self.connection_items.append(connection)
        self.addItem(connection)
        connection.update_path()
        if emit_dirty:
            self.project_dirty.emit()

    def remove_connection(self, connection: ConnectionItem, emit_dirty: bool = True) -> None:
        connection.detach()
        if connection in self.connection_items:
            self.connection_items.remove(connection)
        self.removeItem(connection)
        if emit_dirty:
            self.project_dirty.emit()

    def remove_nodes(self, node_items: list[NodeItem], emit_dirty: bool = True) -> bool:
        removed_any = False
        seen_node_ids: set[str] = set()
        for node_item in node_items:
            node_id = node_item.model.node_id
            if node_id in seen_node_ids or node_id not in self.node_items:
                continue
            seen_node_ids.add(node_id)
            for port in node_item.all_ports():
                for connection in list(port.connections):
                    self.remove_connection(connection, emit_dirty=False)
            self.node_items.pop(node_id, None)
            self.removeItem(node_item)
            removed_any = True

        if removed_any:
            if emit_dirty:
                self.project_dirty.emit()
            self._emit_selected_node()
        return removed_any

    def delete_selected(self) -> None:
        removed_any = False
        for item in list(self.selectedItems()):
            if isinstance(item, ConnectionItem):
                self.remove_connection(item, emit_dirty=False)
                removed_any = True
        removed_any = self.remove_nodes(self.selected_node_items(), emit_dirty=False) or removed_any
        if removed_any:
            self.project_dirty.emit()
            self._emit_selected_node()

    def port_at(self, scene_pos: QPointF, exclude: PortItem | None = None) -> PortItem | None:
        for item in self.items(QRectF(scene_pos.x() - 14, scene_pos.y() - 14, 28, 28)):
            if isinstance(item, PortItem) and item is not exclude:
                return item
        return None

    def selected_node_items(self) -> list[NodeItem]:
        return [item for item in self.selectedItems() if isinstance(item, NodeItem)]

    def _emit_selected_node(self) -> None:
        self.node_selected.emit(self.selected_node_items())


class NodeView(QGraphicsView):
    def __init__(self, scene: NodeScene) -> None:
        super().__init__(scene)
        self._panning = False
        self._last_pan_point = QPoint()
        self._min_zoom = 0.35
        self._max_zoom = 3.0
        self.setObjectName("NodeCanvas")
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor("#f7f9fe"))
        self.setStyleSheet("background: transparent; border: none;")

    def scale_by(self, factor: float) -> None:
        current_scale = self.transform().m11()
        next_scale = current_scale * factor
        if next_scale < self._min_zoom:
            factor = self._min_zoom / current_scale
        elif next_scale > self._max_zoom:
            factor = self._max_zoom / current_scale
        self.scale(factor, factor)

    def zoom_in(self) -> None:
        self.scale_by(1.12)

    def zoom_out(self) -> None:
        self.scale_by(1 / 1.12)

    def reset_zoom(self) -> None:
        center = self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        self.centerOn(center)

    def fit_content(self) -> None:
        scene = self.scene()
        if not isinstance(scene, NodeScene):
            return
        bounds = scene.itemsBoundingRect()
        if bounds.isNull():
            self.reset_zoom()
            self.centerOn(0, 0)
            return
        padded = bounds.adjusted(-84, -84, 84, 84)
        self.fitInView(padded, Qt.KeepAspectRatio)

    def wheelEvent(self, event) -> None:
        self.scale_by(1.12 if event.angleDelta().y() > 0 else 1 / 1.12)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(NODE_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(NODE_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(NODE_MIME_TYPE):
            scene = self.scene()
            if isinstance(scene, NodeScene):
                type_id = bytes(event.mimeData().data(NODE_MIME_TYPE)).decode("utf-8")
                item = scene.create_node(type_id, self.mapToScene(event.position().toPoint()))
                scene.clearSelection()
                item.setSelected(True)
                self.setFocus()
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._last_pan_point = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.pos() - self._last_pan_point
            self._last_pan_point = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            scene = self.scene()
            if isinstance(scene, NodeScene):
                scene.delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            scene = self.scene()
            if isinstance(scene, NodeScene):
                scene.cancel_preview()
                scene.clearSelection()
            event.accept()
            return
        super().keyPressEvent(event)
