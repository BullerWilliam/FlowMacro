from __future__ import annotations

import uuid
from typing import Iterable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QFont,
    QFontMetricsF,
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
    QInputDialog,
    QMenu,
)

from .models import ConfigField, ConnectionModel, GraphModel, NodeDefinition, NodeModel, PortDefinition
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
        self.setAcceptHoverEvents(False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setCursor(Qt.ArrowCursor)
        self.setZValue(3)

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        _ = painter, option, widget

    def hoverEnterEvent(self, event) -> None:
        _ = event

    def hoverLeaveEvent(self, event) -> None:
        _ = event

    def mousePressEvent(self, event) -> None:
        _ = event

    def mouseMoveEvent(self, event) -> None:
        _ = event

    def mouseReleaseEvent(self, event) -> None:
        _ = event

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
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(False)
        self.setCursor(Qt.ArrowCursor)
        self.setZValue(-2 if not preview else 0)
        self.update_path()

    def update_path(self, end_pos: QPointF | None = None) -> None:
        start = self.source_port.scene_center()
        end = self.target_port.scene_center() if self.target_port else (end_pos or self.end_pos)
        self.end_pos = end

        path = QPainterPath(start)
        if self.source_port.definition.type_name == "flow":
            vertical_distance = max(26.0, abs(end.y() - start.y()) * 0.5)
            horizontal_shift = (end.x() - start.x()) * 0.28
            path.cubicTo(
                QPointF(start.x(), start.y() + vertical_distance),
                QPointF(end.x() - horizontal_shift, end.y() - vertical_distance),
                end,
            )
        else:
            horizontal_distance = abs(end.x() - start.x())
            distance = max(54.0, min(150.0, horizontal_distance * 0.5))
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
        _ = painter, option, widget

    def hoverEnterEvent(self, event) -> None:
        _ = event

    def hoverLeaveEvent(self, event) -> None:
        _ = event

    def detach(self) -> None:
        if self in self.source_port.connections:
            self.source_port.connections.remove(self)
        if self.target_port and self in self.target_port.connections:
            self.target_port.connections.remove(self)


class NodeItem(QGraphicsObject):
    def __init__(self, model: NodeModel, definition: NodeDefinition) -> None:
        super().__init__()
        self.model = model
        self.definition = definition
        self.inputs: dict[str, PortItem] = {}
        self.outputs: dict[str, PortItem] = {}
        self.input_socket_rects: dict[str, QRectF] = {}
        self.input_label_rects: dict[str, QRectF] = {}
        self.choice_input_rects: dict[str, QRectF] = {}
        self.output_slot_rects: dict[str, QRectF] = {}
        self.output_label_rects: dict[str, QRectF] = {}
        self.header_rect = QRectF()
        self.output_rail_rect = QRectF()
        self.width = 248.0
        self.height = 120.0
        self._hovered = False
        self._press_scene_pos: QPointF | None = None
        self._drag_started = False
        self._drag_initialized = False
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
        data_inputs = [port for port in self.definition.inputs if port.type_name != "flow"]
        data_outputs = [port for port in self.definition.outputs if port.type_name != "flow"]
        self.input_socket_rects = {}
        self.input_label_rects = {}
        self.choice_input_rects = {}
        self.output_slot_rects = {}
        self.output_label_rects = {}
        self.header_rect = QRectF()
        self.output_rail_rect = QRectF()

        if self.is_command_block:
            title_font = QFont(QApplication.font())
            title_font.setPointSize(10)
            title_font.setBold(True)
            label_font = QFont(QApplication.font())
            label_font.setPointSizeF(7.6)
            label_font.setBold(True)
            output_font = QFont(label_font)

            label_metrics = QFontMetricsF(label_font)
            output_metrics = QFontMetricsF(output_font)
            title_metrics = QFontMetricsF(title_font)

            header_top = 12.0
            header_height = 34.0
            header_gap = 12.0
            body_bottom = 14.0
            left_padding = 24.0
            row_gap = 10.0
            row_min_height = 28.0
            label_gap = 12.0
            rail_padding = 16.0
            rail_port_gap = 8.0
            rail_port_width = 18.0
            max_input_label_width = max(
                [label_metrics.horizontalAdvance(port.label) for port in data_inputs],
                default=0.0,
            )
            title_width = title_metrics.horizontalAdvance(self.definition.title)
            output_rail_width = 0.0

            current_y = header_top + header_height + header_gap
            label_width = max(36.0, max_input_label_width)
            socket_left = left_padding + label_width + label_gap
            max_socket_width = max(110.0, title_width + 36.0)
            row_rects: list[QRectF] = []
            for port in data_inputs:
                child = self.connected_input_node(port.key)
                choice_width = self.choice_input_width(port.key, label_metrics)
                slot_width = max(
                    choice_width,
                    (child.width + 14.0) if child is not None else 110.0,
                )
                slot_height = max(row_min_height, (child.height + 10.0) if child is not None else row_min_height)
                row_rect = QRectF(left_padding, current_y - 1.0, label_width + label_gap + slot_width, slot_height + 2.0)
                row_rects.append(row_rect)
                self.input_label_rects[port.key] = QRectF(left_padding, current_y, label_width, slot_height)
                self.input_socket_rects[port.key] = QRectF(socket_left, current_y, slot_width, slot_height)
                if self.is_choice_input(port.key):
                    self.choice_input_rects[port.key] = QRectF(socket_left, current_y, slot_width, slot_height)
                max_socket_width = max(max_socket_width, slot_width)
                current_y += slot_height + row_gap

            header_width = max(title_width + 48.0, 160.0)
            content_width = left_padding + label_width + label_gap + max_socket_width + 22.0
            self.width = max(260.0, content_width + output_rail_width, header_width + 44.0)

            rail_left = self.width - output_rail_width if output_rail_width else self.width
            if row_rects:
                content_top = row_rects[0].top()
                content_bottom = row_rects[-1].bottom()
            else:
                content_top = header_top + header_height + header_gap
                content_bottom = content_top + row_min_height

            output_span = content_bottom - content_top
            self.height = max(72.0, content_top + output_span + body_bottom)

            self.header_rect = QRectF(left_padding - 4.0, header_top, min(self.width - 24.0, header_width), header_height)
        elif self.is_boolean_reporter:
            current_y = 28.0
            max_socket_width = 68.0
            for port in data_inputs:
                child = self.connected_input_node(port.key)
                slot_width = max(64.0, (child.width + 10.0) if child is not None else 68.0)
                slot_height = max(18.0, (child.height + 6.0) if child is not None else 18.0)
                self.input_socket_rects[port.key] = QRectF(52.0, current_y - 9.0, slot_width, slot_height)
                max_socket_width = max(max_socket_width, slot_width)
                current_y += slot_height + 4.0
            self.width = max(168.0, 76.0 + max_socket_width)
            self.height = max(42.0, current_y + 8.0 if data_inputs else 42.0)
        else:
            if self.is_literal_value_node:
                display_text = self.literal_value_text()
                estimated_width = min(260.0, max(110.0, 28.0 + len(display_text) * 7.2))
                self.width = estimated_width
                self.height = 40.0
                self.prepareGeometryChange()
                total_outputs = len(data_outputs)
                for index, port in enumerate(data_outputs):
                    self.outputs[port.key].setPos(self.width - 10.0, self._reporter_port_y(index, total_outputs))
                self.update()
                return
            if data_inputs:
                title_font = QFont(QApplication.font())
                title_font.setPointSize(9.2)
                title_font.setBold(True)
                label_font = QFont(QApplication.font())
                label_font.setPointSizeF(7.8)
                label_font.setBold(True)

                title_metrics = QFontMetricsF(title_font)
                label_metrics = QFontMetricsF(label_font)
                header_top = 10.0
                header_height = 24.0
                header_gap = 14.0
                body_bottom = 14.0
                left_padding = 18.0
                label_gap = 12.0
                row_gap = 10.0
                row_min_height = 22.0
                right_padding = 18.0

                max_input_label_width = max(
                    [label_metrics.horizontalAdvance(port.label) for port in data_inputs],
                    default=0.0,
                )
                title_width = title_metrics.horizontalAdvance(self.definition.title)
                label_width = max(42.0, max_input_label_width + 6.0)
                socket_left = left_padding + label_width + label_gap
                current_y = header_top + header_height + header_gap
                max_socket_width = 92.0
                for port in data_inputs:
                    child = self.connected_input_node(port.key)
                    choice_width = self.choice_input_width(port.key, label_metrics)
                    slot_width = max(
                        choice_width,
                        (child.width + 12.0) if child is not None else 92.0,
                    )
                    slot_height = max(row_min_height, (child.height + 8.0) if child is not None else row_min_height)
                    self.input_label_rects[port.key] = QRectF(left_padding, current_y, label_width, slot_height)
                    self.input_socket_rects[port.key] = QRectF(socket_left, current_y, slot_width, slot_height)
                    if self.is_choice_input(port.key):
                        self.choice_input_rects[port.key] = QRectF(socket_left, current_y, slot_width, slot_height)
                    max_socket_width = max(max_socket_width, slot_width)
                    current_y += slot_height + row_gap

                self.width = max(176.0, socket_left + max_socket_width + right_padding, title_width + 60.0)
                self.height = max(48.0, current_y + body_bottom - row_gap)
                self.header_rect = QRectF(left_padding - 2.0, header_top, self.width - (left_padding * 2) + 4.0, header_height)
            else:
                title_font = QFont(QApplication.font())
                title_font.setPointSize(9.2)
                title_font.setBold(True)
                title_metrics = QFontMetricsF(title_font)
                self.width = max(150.0, title_metrics.horizontalAdvance(self.definition.title) + 52.0)
                self.height = 42.0

        self.prepareGeometryChange()

        flow_inputs = [port for port in self.definition.inputs if port.type_name == "flow"]
        flow_outputs = [port for port in self.definition.outputs if port.type_name == "flow"]
        for port in flow_inputs:
            self.inputs[port.key].setPos(self.flow_anchor_x(), 0.0)
        for index, port in enumerate(flow_outputs):
            self.outputs[port.key].setPos(self.flow_output_x(index, len(flow_outputs)), self.height)

        if self.is_command_block:
            for port in data_inputs:
                socket = self.input_socket_rects.get(port.key, QRectF(96.0, 20.0, 88.0, 22.0))
                self.inputs[port.key].setPos(socket.right() - 10.0, socket.center().y())
        else:
            total_inputs = len(data_inputs)
            total_outputs = len(data_outputs)
            for index, port in enumerate(data_inputs):
                socket = self.input_socket_rects.get(port.key)
                if socket is not None:
                    self.inputs[port.key].setPos(socket.right() - 10.0, socket.center().y())
                else:
                    self.inputs[port.key].setPos(10.0, self._reporter_port_y(index, total_inputs))
            for index, port in enumerate(data_outputs):
                self.outputs[port.key].setPos(self.width - 10.0, self._reporter_port_y(index, total_outputs))
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-14, -14, self.width + 28, self.height + 28)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)

        accent = QColor(self.definition.color)
        outline_color = accent.darker(118) if self.isSelected() else accent.darker(110)
        if self._hovered and not self.isSelected():
            outline_color = accent.lighter(118)

        block_path = self.block_path()
        shadow_path = QPainterPath(block_path)
        shadow_rect = block_path.boundingRect().translated(3, 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(112, 146, 198, 38))
        painter.drawPath(shadow_path.translated(3, 5))

        if self.isSelected():
            painter.setBrush(with_alpha(accent, 35))
            painter.drawPath(block_path.translated(-2, -2))

        fill_gradient = QLinearGradient(0, 0, self.width, self.height)
        fill_gradient.setColorAt(0.0, accent.lighter(116))
        fill_gradient.setColorAt(1.0, accent.darker(108))
        painter.setPen(QPen(outline_color, 1.3))
        painter.setBrush(fill_gradient)
        painter.drawPath(block_path)

        painter.setPen(with_alpha(QColor("#ffffff"), 55))
        painter.drawPath(self.highlight_path())

        if self.is_literal_value_node:
            value_font = painter.font()
            value_font.setPointSize(9.5)
            value_font.setBold(True)
            painter.setFont(value_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(18, 0, self.width - 36, self.height), Qt.AlignCenter, self.literal_value_text())
        elif not self.is_boolean_reporter:
            painter.setPen(QColor("#ffffff"))
            title_font = painter.font()
            title_font.setPointSize(9.2)
            title_font.setBold(True)
            painter.setFont(title_font)
            if not self.header_rect.isNull():
                painter.drawText(self.header_rect.adjusted(14, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.definition.title)
            else:
                painter.drawText(self.title_rect(), Qt.AlignVCenter | Qt.AlignCenter, self.definition.title)
        else:
            painter.setPen(QColor("#ffffff"))
            title_font = painter.font()
            title_font.setPointSize(10 if self.is_command_block else 9.2)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(self.title_rect(), Qt.AlignVCenter | Qt.AlignLeft, self.definition.title)

        if self.is_command_block:
            self._paint_command_ports(painter)
        elif not self.is_literal_value_node:
            self._paint_reporter_ports(painter)

    def _paint_command_ports(self, painter: QPainter) -> None:
        label_font = painter.font()
        label_font.setPointSize(7.6)
        label_font.setBold(True)
        painter.setFont(label_font)

        for port in self.definition.inputs:
            if port.type_name == "flow":
                continue
            label_rect = self.input_label_rects.get(port.key)
            socket = self.input_socket_rects.get(port.key)
            if label_rect is None or socket is None:
                continue
            painter.setPen(with_alpha(QColor("#ffffff"), 245))
            painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, port.label)
            if self.is_choice_input(port.key):
                self._paint_choice_input(painter, socket, port.key, label_font)
            else:
                self._paint_input_socket(painter, socket, port.type_name, port.key)

        painter.setPen(with_alpha(QColor("#ffffff"), 235))

    def _paint_reporter_ports(self, painter: QPainter) -> None:
        label_font = painter.font()
        label_font.setPointSize(8)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setPen(QColor("#ffffff"))

        if self.is_boolean_reporter:
            painter.drawText(QRectF(18, 8, self.width - 36, 18), Qt.AlignCenter, self.definition.title)

        painter.setFont(label_font)
        painter.setPen(QColor("#ffffff"))
        for port in self.definition.inputs:
            if port.type_name == "flow":
                continue
            label_rect = self.input_label_rects.get(port.key)
            socket = self.input_socket_rects.get(port.key)
            if label_rect is None or socket is None:
                continue
            painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, port.label)
            if self.is_choice_input(port.key):
                self._paint_choice_input(painter, socket, port.key, label_font)
            else:
                self._paint_input_socket(painter, socket, port.type_name, port.key)

    @property
    def is_command_block(self) -> bool:
        return self.definition.is_flow_node

    @property
    def is_boolean_reporter(self) -> bool:
        non_flow_outputs = [port for port in self.definition.outputs if port.type_name != "flow"]
        return not self.definition.is_flow_node and bool(non_flow_outputs) and non_flow_outputs[0].type_name == "boolean"

    @property
    def is_literal_value_node(self) -> bool:
        return self.definition.type_id in {"number_value", "text_value", "boolean_value", "path_value"}

    @property
    def is_multi_input_reporter(self) -> bool:
        return (
            not self.definition.is_flow_node
            and not self.is_literal_value_node
            and any(port.type_name != "flow" for port in self.definition.inputs)
        )

    def flow_anchor_x(self) -> float:
        return 38.0

    def flow_output_x(self, index: int, total: int) -> float:
        if total <= 1:
            return self.flow_anchor_x()
        return 46.0 + index * (self.width - 92.0) / max(total - 1, 1)

    def _reporter_port_y(self, index: int, total: int) -> float:
        if total <= 1:
            return self.height / 2
        top = self.height / 2 - (total - 1) * 9.0
        return top + index * 18.0

    def title_rect(self) -> QRectF:
        if self.is_command_block:
            if not self.header_rect.isNull():
                return self.header_rect.adjusted(20, 0, -16, 0)
            return QRectF(24, 12, self.width - 48, 18)
        if self.is_multi_input_reporter and not self.header_rect.isNull():
            return self.header_rect.adjusted(14, 0, -10, 0)
        return QRectF(18, 8, self.width - 36, 18)

    def detail_rect(self, index: int) -> QRectF:
        if self.is_command_block:
            return QRectF(24, 32 + index * 12, self.width - 48, 12)
        return QRectF(18, 24 + index * 12, self.width - 36, 12)

    def block_path(self) -> QPainterPath:
        if self.is_command_block:
            return self._command_path()
        if self.is_boolean_reporter:
            return self._boolean_path()
        if self.is_multi_input_reporter:
            return self._multi_input_reporter_path()
        return self._reporter_path()

    def highlight_path(self) -> QPainterPath:
        path = self.block_path()
        if self.is_command_block and not self.header_rect.isNull():
            rect = self.header_rect.adjusted(2, 4, -6, -4)
        else:
            rect = path.boundingRect().adjusted(6, 5, -24, -self.height * 0.55)
        highlight = QPainterPath()
        highlight.addRoundedRect(rect, 10, 10)
        return highlight

    def _command_path(self) -> QPainterPath:
        notch_x = self.flow_anchor_x() - 18.0
        notch_w = 26.0
        notch_h = 7.0
        radius = 11.0

        path = QPainterPath(QPointF(radius, 0))
        if self.definition.flow_input_keys:
            path.lineTo(notch_x, 0)
            path.lineTo(notch_x + 4, notch_h)
            path.lineTo(notch_x + notch_w - 4, notch_h)
            path.lineTo(notch_x + notch_w, 0)
        path.lineTo(self.width - radius, 0)
        path.quadTo(self.width, 0, self.width, radius)
        path.lineTo(self.width, self.height - radius)
        path.quadTo(self.width, self.height, self.width - radius, self.height)

        if self.definition.flow_output_keys:
            tab_x = self.flow_anchor_x() - 20.0
            tab_w = 32.0
            tab_h = 8.0
            path.lineTo(tab_x + tab_w, self.height)
            path.lineTo(tab_x + tab_w - 4, self.height + tab_h)
            path.lineTo(tab_x + 4, self.height + tab_h)
            path.lineTo(tab_x, self.height)

        path.lineTo(radius, self.height)
        path.quadTo(0, self.height, 0, self.height - radius)
        path.lineTo(0, radius)
        path.quadTo(0, 0, radius, 0)
        path.closeSubpath()
        return path

    def _reporter_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width, self.height), self.height / 2.2, self.height / 2.2)
        return path

    def _multi_input_reporter_path(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width, self.height), 18.0, 18.0)
        return path

    def _boolean_path(self) -> QPainterPath:
        path = QPainterPath()
        mid_y = self.height / 2
        inset = 20.0
        path.moveTo(inset, 0)
        path.lineTo(self.width - inset, 0)
        path.lineTo(self.width, mid_y)
        path.lineTo(self.width - inset, self.height)
        path.lineTo(inset, self.height)
        path.lineTo(0, mid_y)
        path.closeSubpath()
        return path

    def connected_input_node(self, port_key: str) -> "NodeItem | None":
        port = self.inputs.get(port_key)
        if port is None:
            return None
        for connection in port.connections:
            if connection.target_port is port:
                return connection.source_port.node_item
        return None

    def literal_value_text(self) -> str:
        value = self.model.config.get("value", "")
        if self.definition.type_id == "number_value":
            return str(value)
        if self.definition.type_id == "boolean_value":
            return "true" if bool(value) else "false"
        text = str(value)
        if len(text) > 22:
            text = f"{text[:19]}..."
        if self.definition.type_id == "path_value":
            return text
        return f'"{text}"'

    def config_field_for_port(self, port_key: str) -> ConfigField | None:
        return next((field for field in self.definition.config_fields if field.key == port_key), None)

    def is_choice_input(self, port_key: str) -> bool:
        field = self.config_field_for_port(port_key)
        return field is not None and field.field_type == "choice"

    def choice_input_width(self, port_key: str, metrics: QFontMetricsF | None = None) -> float:
        field = self.config_field_for_port(port_key)
        if field is None or field.field_type != "choice":
            return 0.0
        field_metrics = metrics or QFontMetricsF(QApplication.font())
        current = str(self.model.config.get(port_key, field.default))
        widest = max([current, *field.choices], key=lambda value: field_metrics.horizontalAdvance(str(value)))
        return max(90.0, field_metrics.horizontalAdvance(str(widest)) + 28.0)

    def _paint_choice_input(self, painter: QPainter, rect: QRectF, port_key: str, font: QFont) -> None:
        field = self.config_field_for_port(port_key)
        if field is None:
            return
        value = str(self.model.config.get(port_key, field.default))
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(with_alpha(QColor("#ffffff"), 230))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        choice_font = QFont(font)
        choice_font.setBold(True)
        painter.setFont(choice_font)
        painter.setPen(QColor("#43608f"))
        painter.drawText(rect.adjusted(14, 0, -22, 0), Qt.AlignVCenter | Qt.AlignLeft, value)
        arrow_x = rect.right() - 14.0
        arrow_y = rect.center().y()
        arrow = QPainterPath()
        arrow.moveTo(arrow_x - 4.0, arrow_y - 2.0)
        arrow.lineTo(arrow_x + 4.0, arrow_y - 2.0)
        arrow.lineTo(arrow_x, arrow_y + 3.0)
        arrow.closeSubpath()
        painter.setBrush(QColor("#5d78ab"))
        painter.drawPath(arrow)
        painter.restore()

    def _paint_input_socket(self, painter: QPainter, rect: QRectF, type_name: str, port_key: str) -> None:
        if self.connected_input_node(port_key) is not None:
            return
        field = self.config_field_for_port(port_key)
        painter.setPen(Qt.NoPen)
        painter.setBrush(with_alpha(QColor("#ffffff"), 220))
        if type_name == "boolean":
            diamond = QPainterPath()
            diamond.moveTo(rect.left() + 10, rect.top())
            diamond.lineTo(rect.right() - 10, rect.top())
            diamond.lineTo(rect.right(), rect.center().y())
            diamond.lineTo(rect.right() - 10, rect.bottom())
            diamond.lineTo(rect.left() + 10, rect.bottom())
            diamond.lineTo(rect.left(), rect.center().y())
            diamond.closeSubpath()
            painter.drawPath(diamond)
        else:
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if field is not None and field.field_type != "choice":
            painter.save()
            value_font = painter.font()
            value_font.setPointSizeF(max(7.4, value_font.pointSizeF() if value_font.pointSizeF() > 0 else 8.0))
            value_font.setBold(True)
            painter.setFont(value_font)
            painter.setPen(QColor("#5b6f96"))
            painter.drawText(
                rect.adjusted(12, 0, -12, 0),
                Qt.AlignVCenter | Qt.AlignHCenter,
                self.inline_input_text(port_key),
            )
            painter.restore()

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
            choice_key = self._choice_input_key_at(event.pos())
            if choice_key is not None:
                scene = self.scene()
                if isinstance(scene, NodeScene):
                    scene.clearSelection()
                self.setSelected(True)
                self._show_choice_menu(choice_key, event.screenPos())
                event.accept()
                return
            editable_key = self._editable_input_key_at(event.pos())
            if editable_key is not None:
                scene = self.scene()
                if isinstance(scene, NodeScene):
                    scene.clearSelection()
                self.setSelected(True)
                self._show_input_editor(editable_key)
                event.accept()
                return
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
            if self._drag_started and not self._drag_initialized:
                scene = self.scene()
                if isinstance(scene, NodeScene):
                    scene.begin_block_drag(self)
                self._drag_initialized = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_drag_started = self._drag_started
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if isinstance(scene, NodeScene) and event.button() == Qt.LeftButton:
            scene.end_block_drag()
            if was_drag_started:
                scene.node_drag_finished.emit(self, event.screenPos())
            elif self.isSelected():
                scene.selection_activated.emit(scene.selected_node_items())
        self._press_scene_pos = None
        self._drag_started = False
        self._drag_initialized = False

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

    def _choice_input_key_at(self, pos: QPointF) -> str | None:
        for port_key, rect in self.choice_input_rects.items():
            if rect.contains(pos):
                return port_key
        return None

    def _editable_input_key_at(self, pos: QPointF) -> str | None:
        for port_key, rect in self.input_socket_rects.items():
            if not rect.contains(pos):
                continue
            if self.connected_input_node(port_key) is not None:
                continue
            field = self.config_field_for_port(port_key)
            if field is None or field.field_type == "choice":
                continue
            if field.field_type not in {"text", "int", "float"}:
                continue
            return port_key
        return None

    def _show_choice_menu(self, port_key: str, screen_pos) -> None:
        field = self.config_field_for_port(port_key)
        if field is None or not field.choices:
            return
        menu = QMenu()
        current = str(self.model.config.get(port_key, field.default))
        actions = {}
        for choice in field.choices:
            action = menu.addAction(choice)
            action.setCheckable(True)
            action.setChecked(choice == current)
            actions[action] = choice
        selected = menu.exec(screen_pos)
        if selected is None or selected not in actions:
            return
        next_value = actions[selected]
        if next_value == current:
            return
        self.model.config[port_key] = next_value
        self.refresh_layout()
        scene = self.scene()
        if isinstance(scene, NodeScene):
            scene.handle_node_moved(self)
            scene.project_dirty.emit()

    def inline_input_text(self, port_key: str) -> str:
        field = self.config_field_for_port(port_key)
        if field is None:
            return ""
        value = self.model.config.get(port_key, field.default)
        if field.field_type == "text":
            text = str(value)
            if len(text) > 18:
                text = f"{text[:15]}..."
            return text
        if field.field_type == "int":
            try:
                return str(int(value))
            except (TypeError, ValueError):
                return str(field.default)
        if field.field_type == "float":
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float(field.default)
            return str(int(number)) if number.is_integer() else f"{number:g}"
        return str(value)

    def _show_input_editor(self, port_key: str) -> None:
        field = self.config_field_for_port(port_key)
        if field is None:
            return
        title = self.definition.title
        label = field.label or port_key
        current = self.model.config.get(port_key, field.default)

        if field.field_type == "text":
            next_value, accepted = QInputDialog.getText(None, title, label, text=str(current))
        elif field.field_type == "int":
            default_value = self._coerce_int_value(current, int(field.default))
            minimum = int(field.minimum) if field.minimum is not None else -2147483647
            maximum = int(field.maximum) if field.maximum is not None else 2147483647
            step = int(field.step) if field.step not in {None, 0} else 1
            next_value, accepted = QInputDialog.getInt(None, title, label, default_value, minimum, maximum, step)
        elif field.field_type == "float":
            default_value = self._coerce_float_value(current, float(field.default))
            minimum = float(field.minimum) if field.minimum is not None else -2147483647.0
            maximum = float(field.maximum) if field.maximum is not None else 2147483647.0
            step = float(field.step) if field.step not in {None, 0} else 1.0
            decimals = 4 if step < 1 else 2
            next_value, accepted = QInputDialog.getDouble(
                None,
                title,
                label,
                default_value,
                minimum,
                maximum,
                decimals,
                step,
            )
        else:
            return

        if not accepted:
            return
        self.model.config[port_key] = next_value
        self.refresh_layout()
        scene = self.scene()
        if isinstance(scene, NodeScene):
            scene.handle_node_moved(self)
            scene.project_dirty.emit()

    def _coerce_int_value(self, value: object, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    def _coerce_float_value(self, value: object, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            previous_pos = QPointF(self.model.x, self.model.y)
            current_pos = self.pos()
            delta = current_pos - previous_pos
            self.model.x = float(current_pos.x())
            self.model.y = float(current_pos.y())
            for port in self.all_ports():
                for connection in list(port.connections):
                    connection.update_path()
            scene = self.scene()
            if isinstance(scene, NodeScene):
                if not scene._moving_stack and not delta.isNull():
                    scene.move_drag_stack(self, delta)
                scene.handle_node_moved(self)
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
        self._layouting_flow = False
        self._moving_stack = False
        self._active_drag_root_id: str | None = None
        self.setSceneRect(-6000, -6000, 12000, 12000)
        self.selectionChanged.connect(self._emit_selected_node)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(rect, QColor("#f7f9fe"))

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

        if input_port.node_item.is_choice_input(input_port.definition.key):
            self.error_message.emit("This input uses a dropdown and does not accept blocks.")
            return None

        if not self._port_types_compatible(output_port.definition.type_name, input_port.definition.type_name):
            self.error_message.emit(
                f"Wrong type: '{output_port.definition.type_name}' cannot connect to '{input_port.definition.type_name}'."
            )
            return None

        return output_port, input_port

    def _port_types_compatible(self, output_type: str, input_type: str) -> bool:
        if output_type == input_type:
            return True
        if "any" in {output_type, input_type}:
            return True
        if output_type == "boolean" and input_type in {"number", "text"}:
            return True
        return False

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

        if source_port.definition.type_name != "flow":
            existing_outgoing = self._outgoing_connection_for(source_port)
            if existing_outgoing is not None:
                self.remove_connection(existing_outgoing, emit_dirty=False)

        connection = ConnectionItem(source_port, target_port=target_port)
        source_port.connections.append(connection)
        target_port.connections.append(connection)
        self.connection_items.append(connection)
        self.addItem(connection)
        self._align_connection(connection)
        if source_port.definition.type_name != "flow":
            self.handle_node_moved(source_node)
            self.handle_node_moved(target_node)
        if emit_dirty:
            self.project_dirty.emit()

    def remove_connection(self, connection: ConnectionItem, emit_dirty: bool = True) -> None:
        source_node = connection.source_port.node_item
        target_node = connection.target_port.node_item if connection.target_port is not None else None
        connection_type = connection.source_port.definition.type_name
        connection.detach()
        if connection in self.connection_items:
            self.connection_items.remove(connection)
        self.removeItem(connection)
        if target_node is not None and connection_type != "flow":
            target_node.refresh_layout()
            self.handle_node_moved(target_node)
        if source_node is not None:
            source_node.refresh_layout()
            if connection_type != "flow":
                if self._attachment_connection_for(source_node) is None:
                    source_node.setZValue(1)
                self.handle_node_moved(source_node)
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

    def handle_node_moved(self, node_item: NodeItem) -> None:
        if self._layouting_flow:
            return
        self._layouting_flow = True
        try:
            attached = self._attachment_connection_for(node_item)
            if attached is not None:
                self._align_connection(attached)
            self._layout_descendants(node_item, visited=set())
        finally:
            self._layouting_flow = False

    def _layout_descendants(self, node_item: NodeItem, visited: set[str]) -> None:
        if node_item.model.node_id in visited:
            return
        visited.add(node_item.model.node_id)

        for input_port in node_item.inputs.values():
            if input_port.definition.type_name == "flow":
                continue
            for connection in list(input_port.connections):
                if connection.target_port is not input_port:
                    continue
                self._align_connection(connection)
                self._layout_descendants(connection.source_port.node_item, visited)

        for output_port in node_item.outputs.values():
            for connection in list(output_port.connections):
                target_port = connection.target_port
                if target_port is None:
                    continue
                self._align_connection(connection)
                if output_port.definition.type_name == "flow":
                    self._layout_descendants(target_port.node_item, visited)
                else:
                    self._layout_descendants(output_port.node_item, visited)

    def _stack_flow_connection(self, source_node: NodeItem, target_node: NodeItem, output_key: str) -> None:
        output_keys = source_node.definition.flow_output_keys
        if output_key not in output_keys:
            return
        index = output_keys.index(output_key)
        target_x = source_node.pos().x() + source_node.flow_output_x(index, len(output_keys)) - target_node.flow_anchor_x()
        target_y = source_node.pos().y() + source_node.height
        target_node.setPos(target_x, target_y)

    def begin_block_drag(self, node_item: NodeItem) -> None:
        self._active_drag_root_id = node_item.model.node_id
        if node_item.is_command_block:
            incoming = self._incoming_flow_connection_for(node_item)
            if incoming is not None:
                self.remove_connection(incoming, emit_dirty=False)
        else:
            attachment = self._attachment_connection_for(node_item)
            if attachment is not None:
                self.remove_connection(attachment, emit_dirty=False)
        self.handle_node_moved(node_item)

    def end_block_drag(self) -> None:
        self._active_drag_root_id = None

    def move_drag_stack(self, root_node: NodeItem, delta: QPointF) -> None:
        if delta.isNull():
            return
        if self._active_drag_root_id != root_node.model.node_id:
            return
        descendants = self._flow_descendants(root_node)
        if not descendants:
            return
        self._moving_stack = True
        try:
            for descendant in descendants:
                descendant.setPos(descendant.pos() + delta)
        finally:
            self._moving_stack = False

    def _incoming_flow_connection_for(self, node_item: NodeItem) -> ConnectionItem | None:
        for port in node_item.inputs.values():
            if port.definition.type_name != "flow":
                continue
            for connection in port.connections:
                if connection.target_port is port:
                    return connection
        return None

    def _flow_descendants(self, root_node: NodeItem) -> list[NodeItem]:
        descendants: list[NodeItem] = []
        queue = [root_node]
        seen = {root_node.model.node_id}
        while queue:
            current = queue.pop(0)
            for output_port in current.outputs.values():
                if output_port.definition.type_name != "flow":
                    continue
                for connection in output_port.connections:
                    target_port = connection.target_port
                    if target_port is None:
                        continue
                    target_node = target_port.node_item
                    if target_node.model.node_id in seen:
                        continue
                    seen.add(target_node.model.node_id)
                    descendants.append(target_node)
                    queue.append(target_node)
        return descendants

    def snap_released_node(self, node_item: NodeItem) -> bool:
        if node_item.is_command_block:
            if self._snap_command_block(node_item):
                return True
        return self._snap_reporter_block(node_item)

    def _snap_command_block(self, node_item: NodeItem) -> bool:
        flow_inputs = [port for port in node_item.inputs.values() if port.definition.type_name == "flow"]
        if not flow_inputs:
            return False
        input_port = flow_inputs[0]
        input_center = input_port.scene_center()

        best_match: tuple[float, PortItem] | None = None
        for candidate in self.node_items.values():
            if candidate is node_item or candidate.model.node_id in {child.model.node_id for child in self._flow_descendants(node_item)}:
                continue
            for output_port in candidate.outputs.values():
                if output_port.definition.type_name != "flow":
                    continue
                connection = self._outgoing_connection_for(output_port)
                if connection is not None:
                    continue
                output_center = output_port.scene_center()
                distance = (output_center - input_center).manhattanLength()
                if distance > 90:
                    continue
                if best_match is None or distance < best_match[0]:
                    best_match = (distance, output_port)

        if best_match is None:
            return False

        self._connect_ports(best_match[1], input_port)
        return True

    def _snap_reporter_block(self, node_item: NodeItem) -> bool:
        output_ports = [port for port in node_item.outputs.values() if port.definition.type_name != "flow"]
        if not output_ports:
            return False

        best_match: tuple[float, PortItem, PortItem] | None = None
        for output_port in output_ports:
            output_center = output_port.scene_center()
            for candidate in self.node_items.values():
                if candidate is node_item:
                    continue
                for input_port in candidate.inputs.values():
                    if input_port.definition.type_name == "flow":
                        continue
                    if candidate.is_choice_input(input_port.definition.key):
                        continue
                    if not self._port_types_compatible(output_port.definition.type_name, input_port.definition.type_name):
                        continue
                    input_center = input_port.scene_center()
                    distance = (output_center - input_center).manhattanLength()
                    if distance > 120:
                        continue
                    if best_match is None or distance < best_match[0]:
                        best_match = (distance, output_port, input_port)

        if best_match is None:
            return False

        _, output_port, input_port = best_match
        self._connect_ports(output_port, input_port)
        return True

    def _connect_ports(self, output_port: PortItem, input_port: PortItem) -> bool:
        normalized = self._normalize_ports(output_port, input_port)
        if normalized is None:
            return False
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
            return False
        model = ConnectionModel(
            from_node_id=output_port.node_item.model.node_id,
            from_port_key=output_port.definition.key,
            to_node_id=input_port.node_item.model.node_id,
            to_port_key=input_port.definition.key,
        )
        self._add_connection_from_model(model, emit_dirty=True)
        return True

    def _outgoing_connection_for(self, output_port: PortItem) -> ConnectionItem | None:
        return next((connection for connection in output_port.connections if connection.source_port is output_port), None)

    def _align_connection(self, connection: ConnectionItem) -> None:
        source_port = connection.source_port
        target_port = connection.target_port
        if target_port is None:
            connection.update_path()
            return

        source_node = source_port.node_item
        target_node = target_port.node_item
        source_node.refresh_layout()
        target_node.refresh_layout()

        if source_port.definition.type_name == "flow":
            self._stack_flow_connection(source_node, target_node, source_port.definition.key)
            connection.update_path()
            return

        source_node.setZValue(max(2, target_node.zValue() + 1))
        target_center = target_port.scene_center()
        source_center = source_port.scene_center()
        delta = target_center - source_center
        source_node.setPos(source_node.pos() + delta)
        connection.update_path()

    def _attachment_connection_for(self, node_item: NodeItem) -> ConnectionItem | None:
        for port in node_item.inputs.values():
            if port.definition.type_name != "flow":
                continue
            for connection in port.connections:
                if connection.target_port is port:
                    return connection

        for port in node_item.outputs.values():
            if port.definition.type_name == "flow":
                continue
            for connection in port.connections:
                if connection.source_port is port and connection.target_port is not None:
                    return connection
        return None


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
