from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from .models import ConfigField


class InspectorPanel(QFrame):
    config_changed = Signal()
    pick_screen_position_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("InspectorPanel")
        self.setMinimumWidth(320)
        self.current_node: NodeItem | None = None

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

        self.form_layout = QFormLayout(self.form_host)
        self.form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form_layout.setContentsMargins(0, 4, 0, 0)
        self.form_layout.setSpacing(10)

    def set_node(self, node_item: NodeItem | None) -> None:
        self.current_node = node_item
        self._clear_form()

        if node_item is None:
            self.title_label.setText("Inspector")
            self.subtitle.setText("Select a node to inspect its configuration.")
            return

        self.title_label.setText(node_item.definition.title)
        self.subtitle.setText(node_item.definition.description)
        if not node_item.definition.config_fields:
            empty = QLabel("This node has no editable configuration.")
            empty.setObjectName("DrawerMuted")
            empty.setWordWrap(True)
            self.form_layout.addRow(empty)
        else:
            for field in node_item.definition.config_fields:
                widget = self._build_editor(field, node_item)
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
                self.form_layout.addRow(field.label, field_host)

        if node_item.model.type_id == "get_pixel":
            pick_button = QPushButton("Pick Screen Position")
            pick_button.clicked.connect(lambda: self.pick_screen_position_requested.emit(node_item))
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
            self.form_layout.addRow("Screen Picker", field_host)

    def _clear_form(self) -> None:
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)

    def _build_editor(self, field: ConfigField, node_item: NodeItem) -> QWidget:
        value = node_item.model.config.get(field.key, field.default)

        def apply_value(new_value):
            node_item.model.config[field.key] = new_value
            node_item.refresh_layout()
            node_item.update()
            self.config_changed.emit()

        if field.field_type == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(value))
            editor.stateChanged.connect(lambda _: apply_value(editor.isChecked()))
            return editor

        if field.field_type == "choice":
            editor = QComboBox()
            editor.addItems(field.choices)
            if value in field.choices:
                editor.setCurrentText(str(value))
            editor.currentTextChanged.connect(apply_value)
            return editor

        if field.field_type == "int":
            editor = QSpinBox()
            editor.setRange(int(field.minimum or -999999), int(field.maximum or 999999))
            editor.setSingleStep(int(field.step or 1))
            editor.setValue(int(value))
            editor.valueChanged.connect(apply_value)
            return editor

        if field.field_type == "float":
            editor = QDoubleSpinBox()
            editor.setDecimals(3)
            editor.setRange(float(field.minimum or -1_000_000.0), float(field.maximum or 1_000_000.0))
            editor.setSingleStep(float(field.step or 1.0))
            editor.setValue(float(value))
            editor.valueChanged.connect(apply_value)
            return editor

        editor = QLineEdit(str(value))
        editor.textChanged.connect(apply_value)
        return editor
