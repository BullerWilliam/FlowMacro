from __future__ import annotations

import json
from pathlib import Path

from .models import ConnectionModel, GraphModel, NodeModel

FILE_TYPE = "FlowMacroProject"
FILE_VERSION = 1


def save_graph(graph: GraphModel, path: Path) -> None:
    payload = {
        "file_type": FILE_TYPE,
        "version": FILE_VERSION,
        "app": "FlowMacro Studio",
        "nodes": [
            {
                "id": node.node_id,
                "type": node.type_id,
                "position": {"x": node.x, "y": node.y},
                "config": node.config,
            }
            for node in graph.nodes
        ],
        "connections": [
            {
                "from_node": connection.from_node_id,
                "from_port": connection.from_port_key,
                "to_node": connection.to_node_id,
                "to_port": connection.to_port_key,
            }
            for connection in graph.connections
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_graph(path: Path) -> GraphModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("file_type") != FILE_TYPE:
        raise ValueError("This file is not a FlowMacroProject (.fmp).")

    nodes = [
        NodeModel(
            node_id=node_payload["id"],
            type_id=node_payload["type"],
            x=float(node_payload["position"]["x"]),
            y=float(node_payload["position"]["y"]),
            config=dict(node_payload.get("config", {})),
        )
        for node_payload in payload.get("nodes", [])
    ]
    connections = [
        ConnectionModel(
            from_node_id=connection_payload["from_node"],
            from_port_key=connection_payload["from_port"],
            to_node_id=connection_payload["to_node"],
            to_port_key=connection_payload["to_port"],
        )
        for connection_payload in payload.get("connections", [])
    ]
    return GraphModel(nodes=nodes, connections=connections)
