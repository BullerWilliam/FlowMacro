from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .canvas import NodeItem
from .models import ConfigField, NodeDefinition


class InspectorPanel(QFrame):
    config_changed = Signal()
    pick_screen_position_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("InspectorPanel")
        self.setMinimumWidth(320)
        self.current_nodes: list[NodeItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.title_label = QLabel("Inspector")
        self.title_label.setObjectName("DrawerTitle")
        layout.addWidget(self.title_label)

        self.subtitle = QLabel("Select a node to inspect its configuration.")
        self.subtitle.setObjectName("DrawerMuted")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll, 1)

        self.form_host = QWidget()
        scroll.setWidget(self.form_host)

        self.content_layout = QVBoxLayout(self.form_host)
        self.content_layout.setContentsMargins(0, 4, 0, 0)
        self.content_layout.setSpacing(12)
        self.content_layout.setAlignment(Qt.AlignTop)

    def set_nodes(self, node_items: list[NodeItem] | None) -> None:
        self.current_nodes = list(node_items or [])
        self._clear_form()

        if not self.current_nodes:
            self.title_label.setText("Inspector")
            self.subtitle.setText("Select a node to inspect its configuration.")
            return

        if len(self.current_nodes) == 1:
            node_item = self.current_nodes[0]
            self.title_label.setText(node_item.definition.title)
            self.subtitle.setText(node_item.definition.description)
            self.content_layout.addWidget(self._build_group_section(node_item.definition, [node_item], show_header=False))
            return

        grouped = self._group_nodes_by_type(self.current_nodes)
        self.title_label.setText("Multi-Selection")
        self.subtitle.setText(
            f"Editing {len(self.current_nodes)} nodes across {len(grouped)} types. "
            "Mixed values show ? and changes apply to every selected node of that type."
        )
        for definition, nodes in grouped:
            self.content_layout.addWidget(self._build_group_section(definition, nodes, show_header=True))

    def _group_nodes_by_type(self, node_items: list[NodeItem]) -> list[tuple[NodeDefinition, list[NodeItem]]]:
        grouped: dict[str, list[NodeItem]] = {}
        for node_item in node_items:
            grouped.setdefault(node_item.model.type_id, []).append(node_item)
        ordered = sorted(grouped.values(), key=lambda nodes: nodes[0].definition.title.lower())
        return [(nodes[0].definition, nodes) for nodes in ordered]

    def _build_group_section(
        self,
        definition: NodeDefinition,
        node_items: list[NodeItem],
        show_header: bool,
    ) -> QWidget:
        section = QFrame()
        section.setObjectName("InspectorGroup")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(14, 14, 14, 14)
        section_layout.setSpacing(10)

        if show_header:
            title = QLabel(definition.title)
            title.setObjectName("InspectorGroupTitle")
            section_layout.addWidget(title)

            meta = QLabel(f"{definition.category.upper()} - {len(node_items)} selected")
            meta.setObjectName("InspectorGroupMeta")
            section_layout.addWidget(meta)

            description = QLabel(definition.description)
            description.setObjectName("DrawerMuted")
            description.setWordWrap(True)
            section_layout.addWidget(description)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        if not definition.config_fields and definition.type_id != "get_pixel":
            empty = QLabel("This node has no editable configuration.")
            empty.setObjectName("DrawerMuted")
            empty.setWordWrap(True)
            form.addRow(empty)
        else:
            for field in definition.config_fields:
                widget = self._build_editor(field, node_items)
                help_label = QLabel(field.help_text or field.label)
                help_label.setObjectName("DrawerMuted")
                help_label.setWordWrap(True)

                wrapper = QVBoxLayout()
                wrapper.setContentsMargins(0, 0, 0, 0)
                wrapper.setSpacing(5)
                wrapper.addWidget(widget)
                wrapper.addWidget(help_label)

                field_host = QWidget()
                field_host.setLayout(wrapper)
                form.addRow(field.label, field_host)

        if definition.type_id == "get_pixel":
            pick_button = QPushButton("Pick Screen Position")
            pick_button.clicked.connect(
                lambda _checked=False, targets=list(node_items): self.pick_screen_position_requested.emit(targets)
            )
            help_label = QLabel("Click this to pick X/Y directly from the live screen.")
            help_label.setObjectName("DrawerMuted")
            help_label.setWordWrap(True)

            wrapper = QVBoxLayout()
            wrapper.setContentsMargins(0, 0, 0, 0)
            wrapper.setSpacing(5)
            wrapper.addWidget(pick_button)
            wrapper.addWidget(help_label)

            field_host = QWidget()
            field_host.setLayout(wrapper)
            form.addRow("Screen Picker", field_host)

        section_layout.addWidget(form_host)
        return section

    def _clear_form(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _shared_value(self, field: ConfigField, node_items: list[NodeItem]) -> tuple[bool, Any]:
        values = [node_item.model.config.get(field.key, field.default) for node_item in node_items]
        first = values[0]
        return any(value != first for value in values[1:]), first

    def _apply_value(self, field: ConfigField, node_items: list[NodeItem], new_value: Any) -> None:
        changed = False
        for node_item in node_items:
            if node_item.model.config.get(field.key, field.default) == new_value:
                continue
            node_item.model.config[field.key] = new_value
            node_item.refresh_layout()
            node_item.update()
            changed = True
        if changed:
            self.config_changed.emit()

    def _build_editor(self, field: ConfigField, node_items: list[NodeItem]) -> QWidget:
        is_mixed, value = self._shared_value(field, node_items)
        is_multi_edit = len(node_items) > 1

        if field.field_type == "bool":
            editor = QCheckBox()
            editor.setTristate(is_mixed)
            editor.setCheckState(Qt.PartiallyChecked if is_mixed else (Qt.Checked if bool(value) else Qt.Unchecked))

            def handle_state_change(state: int) -> None:
                if state == Qt.PartiallyChecked:
                    return
                self._apply_value(field, node_items, state == Qt.Checked)

            editor.stateChanged.connect(handle_state_change)
            return editor

        if field.field_type == "choice":
            editor = QComboBox()
            if is_mixed:
                editor.addItem("?", "__mixed__")
                editor.setToolTip("Selected nodes have different values for this field.")
            for choice in field.choices:
                editor.addItem(choice, choice)
            if is_mixed:
                editor.setCurrentIndex(0)
            elif value in field.choices:
                editor.setCurrentText(str(value))

            def handle_choice_change(index: int) -> None:
                choice_value = editor.itemData(index)
                if choice_value == "__mixed__":
                    return
                self._apply_value(field, node_items, choice_value)

            editor.currentIndexChanged.connect(handle_choice_change)
            return editor

        if field.field_type == "int":
            if is_multi_edit:
                editor = QLineEdit()
                minimum = int(field.minimum if field.minimum is not None else -999999)
                maximum = int(field.maximum if field.maximum is not None else 999999)
                editor.setValidator(QIntValidator(minimum, maximum, editor))
                if is_mixed:
                    editor.setPlaceholderText("?")
                    editor.setToolTip("Selected nodes have different values for this field.")
                else:
                    editor.setText(str(int(value)))

                def handle_int_text(text: str) -> None:
                    stripped = text.strip()
                    if not stripped:
                        return
                    try:
                        parsed = int(stripped)
                    except ValueError:
                        return
                    self._apply_value(field, node_items, parsed)

                editor.textEdited.connect(handle_int_text)
                return editor

            editor = QSpinBox()
            editor.setRange(
                int(field.minimum if field.minimum is not None else -999999),
                int(field.maximum if field.maximum is not None else 999999),
            )
            editor.setSingleStep(int(field.step if field.step is not None else 1))
            editor.setValue(int(value))
            editor.valueChanged.connect(lambda new_value: self._apply_value(field, node_items, int(new_value)))
            return editor

        if field.field_type == "float":
            if is_multi_edit:
                editor = QLineEdit()
                minimum = float(field.minimum if field.minimum is not None else -1_000_000.0)
                maximum = float(field.maximum if field.maximum is not None else 1_000_000.0)
                validator = QDoubleValidator(minimum, maximum, 6, editor)
                validator.setNotation(QDoubleValidator.StandardNotation)
                editor.setValidator(validator)
                if is_mixed:
                    editor.setPlaceholderText("?")
                    editor.setToolTip("Selected nodes have different values for this field.")
                else:
                    editor.setText(str(float(value)))

                def handle_float_text(text: str) -> None:
                    stripped = text.strip()
                    if not stripped:
                        return
                    try:
                        parsed = float(stripped)
                    except ValueError:
                        return
                    self._apply_value(field, node_items, parsed)

                editor.textEdited.connect(handle_float_text)
                return editor

            editor = QDoubleSpinBox()
            editor.setDecimals(3)
            editor.setRange(
                float(field.minimum if field.minimum is not None else -1_000_000.0),
                float(field.maximum if field.maximum is not None else 1_000_000.0),
            )
            editor.setSingleStep(float(field.step if field.step is not None else 1.0))
            editor.setValue(float(value))
            editor.valueChanged.connect(lambda new_value: self._apply_value(field, node_items, float(new_value)))
            return editor

        editor = QLineEdit()
        if is_mixed:
            editor.setPlaceholderText("?")
            editor.setToolTip("Selected nodes have different values for this field.")
        else:
            editor.setText(str(value))
        editor.textEdited.connect(lambda text: self._apply_value(field, node_items, text))
        return editor
