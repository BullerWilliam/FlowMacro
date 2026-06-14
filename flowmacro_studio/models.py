from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PORT_COLORS: dict[str, str] = {
    "flow": "#3DD9D6",
    "number": "#FFB454",
    "text": "#59A5FF",
    "boolean": "#7EE787",
    "any": "#8EA7CA",
    "files": "#FFD166",
    "image": "#FF7AA2",
    "pixel": "#FF7B72",
}


@dataclass(slots=True)
class PortDefinition:
    key: str
    label: str
    type_name: str
    is_output: bool


@dataclass(slots=True)
class ConfigField:
    key: str
    label: str
    field_type: str
    default: Any
    help_text: str = ""
    choices: list[str] = field(default_factory=list)
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None


@dataclass(slots=True)
class NodeDefinition:
    type_id: str
    title: str
    category: str
    description: str
    color: str
    inputs: list[PortDefinition]
    outputs: list[PortDefinition]
    config_fields: list[ConfigField] = field(default_factory=list)
    visible_in_palette: bool = True

    def default_config(self) -> dict[str, Any]:
        return {field.key: field.default for field in self.config_fields}

    @property
    def flow_input_keys(self) -> list[str]:
        return [port.key for port in self.inputs if port.type_name == "flow"]

    @property
    def flow_output_keys(self) -> list[str]:
        return [port.key for port in self.outputs if port.type_name == "flow"]

    @property
    def is_flow_node(self) -> bool:
        return bool(self.flow_input_keys or self.flow_output_keys)


@dataclass(slots=True)
class NodeModel:
    node_id: str
    type_id: str
    x: float
    y: float
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectionModel:
    from_node_id: str
    from_port_key: str
    to_node_id: str
    to_port_key: str


@dataclass(slots=True)
class GraphModel:
    nodes: list[NodeModel] = field(default_factory=list)
    connections: list[ConnectionModel] = field(default_factory=list)
