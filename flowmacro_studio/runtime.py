from __future__ import annotations

import atexit
import base64
import io
import math
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .models import ConnectionModel, GraphModel, NodeDefinition, NodeModel


_HELD_KEYS: set[str] = set()
_HELD_MOUSE_BUTTONS: set[str] = set()
_HELD_INPUTS_LOCK = threading.Lock()


def _release_all_held_inputs() -> None:
    with _HELD_INPUTS_LOCK:
        keys = list(_HELD_KEYS)
        _HELD_KEYS.clear()
        buttons = list(_HELD_MOUSE_BUTTONS)
        _HELD_MOUSE_BUTTONS.clear()
    if not keys and not buttons:
        return
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        for key in reversed(keys):
            try:
                pyautogui.keyUp(key)
            except Exception:
                continue
        for button in reversed(buttons):
            try:
                pyautogui.mouseUp(button=button)
            except Exception:
                continue
    except Exception:
        return


atexit.register(_release_all_held_inputs)


class GraphRuntime:
    def __init__(
        self,
        graph: GraphModel,
        catalog: dict[str, NodeDefinition],
        project_path: Path | None,
        log: Callable[[Any], None],
        should_stop: Callable[[], bool],
    ) -> None:
        self.graph = graph
        self.catalog = catalog
        self.project_path = project_path
        self.log = log
        self.should_stop = should_stop
        self.nodes = {node.node_id: node for node in graph.nodes}
        self.outputs_cache: dict[str, dict[str, Any]] = {}
        self.pure_cache: dict[str, dict[str, Any]] = {}
        self.incoming_data: dict[tuple[str, str], ConnectionModel] = {}
        self.outgoing_flow: dict[tuple[str, str], list[ConnectionModel]] = {}
        self.variables: dict[str, Any] = {}
        self.step_count = 0
        self.max_steps = 1000
        self.base_dir = (project_path.parent if project_path else Path.cwd()).resolve()

        for connection in graph.connections:
            target_node = self.nodes.get(connection.to_node_id)
            source_node = self.nodes.get(connection.from_node_id)
            if not target_node or not source_node:
                continue
            source_definition = self.catalog[source_node.type_id]
            source_port = next(
                (port for port in source_definition.outputs if port.key == connection.from_port_key),
                None,
            )
            if source_port is None:
                continue
            if source_port.type_name == "flow":
                self.outgoing_flow.setdefault(
                    (connection.from_node_id, connection.from_port_key),
                    [],
                ).append(connection)
            else:
                self.incoming_data[(connection.to_node_id, connection.to_port_key)] = connection

    def run(self) -> None:
        start_nodes = [node for node in self.graph.nodes if node.type_id == "start"]
        if not start_nodes:
            raise RuntimeError("Add a Start node before running the macro.")

        self.log("FlowMacro Studio runtime started.")
        try:
            for node in start_nodes:
                self._walk(node.node_id)
            self.log("FlowMacro Studio runtime finished.")
        finally:
            released_keys, released_buttons = self._release_held_inputs()
            if released_keys:
                self.log(f"[Keyboard] Released {released_keys} held key(s).")
            if released_buttons:
                self.log(f"[Mouse] Released {released_buttons} held button(s).")

    def _walk(self, node_id: str) -> None:
        if self.should_stop():
            raise RuntimeError("Execution stopped.")
        self.step_count += 1
        if self.step_count > self.max_steps:
            raise RuntimeError("Execution stopped after hitting the safety step limit.")

        node = self.nodes[node_id]
        definition = self.catalog[node.type_id]
        next_flow_ports = self._execute_node(node, definition)
        for output_key in next_flow_ports:
            self._walk_flow_output(node.node_id, output_key)

    def _execute_node(self, node: NodeModel, definition: NodeDefinition) -> list[str]:
        if node.type_id == "start":
            self.outputs_cache[node.node_id] = {}
            self.log("[Start] Macro execution triggered.")
            return ["next"]

        if node.type_id == "delay":
            duration_ms = max(0, int(self._value_for(node, "duration_ms", 0)))
            self.log(f"[Delay] Waiting {duration_ms} ms.")
            self._sleep_with_stop(duration_ms / 1000)
            self.outputs_cache[node.node_id] = {}
            return ["next"]

        if node.type_id == "branch":
            condition = bool(self._value_for(node, "condition", False))
            self.outputs_cache[node.node_id] = {"condition": condition}
            self.log(f"[Branch] Condition evaluated to {condition}.")
            return ["true_flow"] if condition else ["false_flow"]

        if node.type_id == "if_block":
            condition = bool(self._value_for(node, "condition", False))
            self.outputs_cache[node.node_id] = {"condition": condition}
            self.log(f"[If] Condition evaluated to {condition}.")
            return ["true_flow", "next"] if condition else ["next"]

        if node.type_id == "if_else_block":
            condition = bool(self._value_for(node, "condition", False))
            self.outputs_cache[node.node_id] = {"condition": condition}
            self.log(f"[If Else] Condition evaluated to {condition}.")
            return ["true_flow", "next"] if condition else ["false_flow", "next"]

        if node.type_id == "repeat_block":
            count = max(0, int(self._value_for(node, "count", 0)))
            self.outputs_cache[node.node_id] = {"count": count}
            self.log(f"[Repeat] Running nested stack {count} time(s).")
            for _ in range(count):
                self._walk_flow_output(node.node_id, "body")
            return ["next"]

        if node.type_id == "repeat_until_block":
            self.outputs_cache[node.node_id] = {}
            self.log("[Repeat Until] Running nested stack until condition becomes true.")
            while not bool(self._value_for(node, "condition", False)):
                self._walk_flow_output(node.node_id, "body")
                if self.should_stop():
                    raise RuntimeError("Execution stopped.")
            self.log("[Repeat Until] Condition became true.")
            return ["next"]

        if node.type_id == "forever_block":
            self.outputs_cache[node.node_id] = {}
            self.log("[Forever] Running nested stack until stopped.")
            while not self.should_stop():
                self._walk_flow_output(node.node_id, "body")
            return []

        if node.type_id == "wait_until":
            self.outputs_cache[node.node_id] = {}
            self.log("[Wait Until] Waiting for condition to become true.")
            while not bool(self._value_for(node, "condition", False)):
                if self.should_stop():
                    raise RuntimeError("Execution stopped.")
                self._sleep_with_stop(0.05)
            self.log("[Wait Until] Condition became true.")
            return ["next"]

        if node.type_id == "log_text":
            value = self._value_for(node, "value", node.config.get("value", ""))
            self.outputs_cache[node.node_id] = {"value": value}
            self.log(value)
            return ["next"]

        if node.type_id == "set_variable":
            name = self._normalize_variable_name(self._value_for(node, "name", ""))
            value = self._coerce_variable_storage_value(self._value_for(node, "value", "0"))
            self.variables[name] = value
            self.pure_cache.clear()
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Set Variable] {name} = {self._format_variable_value(value)}")
            return ["next"]

        if node.type_id == "change_variable":
            name = self._normalize_variable_name(self._value_for(node, "name", ""))
            amount = float(self._value_for(node, "amount", 0))
            current = self.variables.get(name, 0)
            next_value = self._coerce_variable_number(current) + amount
            if next_value.is_integer():
                stored_value: Any = int(next_value)
            else:
                stored_value = next_value
            self.variables[name] = stored_value
            self.pure_cache.clear()
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Change Variable] {name} -> {self._format_variable_value(stored_value)}")
            return ["next"]

        if node.type_id == "get_files":
            folder_value = str(self._value_for(node, "folder", "."))
            pattern = str(self._value_for(node, "pattern", "*.*"))
            resolved_folder = self._resolve_path(folder_value)
            files = sorted(str(path.resolve()) for path in resolved_folder.glob(pattern))
            self.outputs_cache[node.node_id] = {"files": files}
            self.log(f"[Get Files] Found {len(files)} file(s) in {resolved_folder}.")
            return ["next"]

        if node.type_id == "write_text_file":
            raw_path = str(self._value_for(node, "path", "output.txt"))
            text = str(self._value_for(node, "text", ""))
            mode = str(node.config.get("mode", "overwrite"))
            resolved_file = self._prepare_output_file(raw_path)
            resolved_file.parent.mkdir(parents=True, exist_ok=True)
            write_mode = "a" if mode == "append" else "w"
            resolved_file.write_text(text, encoding="utf-8") if write_mode == "w" else self._append_text_file(
                resolved_file, text
            )
            result = str(resolved_file.resolve())
            self.outputs_cache[node.node_id] = {"saved_path": result}
            self.log(f"[Write Text File] Saved {result}.")
            return ["next"]

        if node.type_id == "delete_file":
            raw_path = str(self._value_for(node, "path", "output.txt"))
            missing_ok = bool(node.config.get("missing_ok", True))
            resolved_file = self._resolve_path(raw_path)
            deleted = self._delete_file(resolved_file, missing_ok=missing_ok)
            self.outputs_cache[node.node_id] = {"deleted": deleted}
            self.log(f"[Delete File] {'Deleted' if deleted else 'Skipped'} {resolved_file}.")
            return ["next"]

        if node.type_id == "copy_file":
            source = self._require_file(self._resolve_path(str(self._value_for(node, "source", ""))))
            destination = self._resolve_path(str(self._value_for(node, "destination", "")))
            overwrite = bool(node.config.get("overwrite", True))
            if source.resolve() == destination.resolve():
                raise RuntimeError("Copy File source and destination must be different.")
            self._prepare_destination_file(destination, overwrite=overwrite)
            destination.parent.mkdir(parents=True, exist_ok=True)
            copied_path = shutil.copy2(source, destination)
            result = str(Path(copied_path).resolve())
            self.outputs_cache[node.node_id] = {"saved_path": result}
            self.log(f"[Copy File] Copied {source} -> {result}.")
            return ["next"]

        if node.type_id == "move_file":
            source = self._require_file(self._resolve_path(str(self._value_for(node, "source", ""))))
            destination = self._resolve_path(str(self._value_for(node, "destination", "")))
            overwrite = bool(node.config.get("overwrite", True))
            if source.resolve() == destination.resolve():
                result = str(source.resolve())
                self.outputs_cache[node.node_id] = {"saved_path": result}
                self.log(f"[Move File] Source and destination are the same: {result}.")
                return ["next"]
            self._prepare_destination_file(destination, overwrite=overwrite)
            destination.parent.mkdir(parents=True, exist_ok=True)
            moved_path = shutil.move(str(source), str(destination))
            result = str(Path(moved_path).resolve())
            self.outputs_cache[node.node_id] = {"saved_path": result}
            self.log(f"[Move File] Moved {source} -> {result}.")
            return ["next"]

        if node.type_id == "get_pixel":
            import pyautogui

            pyautogui.FAILSAFE = True
            x = int(self._value_for(node, "x", 0))
            y = int(self._value_for(node, "y", 0))
            red, green, blue = pyautogui.pixel(x, y)
            self.outputs_cache[node.node_id] = self._pixel_outputs(x, y, red, green, blue)
            self.log(f"[Get Pixel from Screen] ({x}, {y}) -> rgb({red}, {green}, {blue}).")
            return ["next"]

        if node.type_id == "get_pixel_from_image":
            from PIL import Image

            image_value = self._value_for(node, "image", None)
            image_bytes = self._resolve_image_data(image_value, "")
            x = int(self._value_for(node, "x", 0))
            y = int(self._value_for(node, "y", 0))
            with Image.open(io.BytesIO(image_bytes)) as image_file:
                image = image_file.convert("RGB")
                if x < 0 or y < 0 or x >= image.width or y >= image.height:
                    raise RuntimeError(
                        f"Image pixel ({x}, {y}) is outside the image bounds {image.width}x{image.height}."
                    )
                red, green, blue = image.getpixel((x, y))
            self.outputs_cache[node.node_id] = self._pixel_outputs(x, y, red, green, blue)
            image_label = self._describe_image_source(image_value, "")
            self.log(f"[Get Pixel from Image] {image_label} @ ({x}, {y}) -> rgb({red}, {green}, {blue}).")
            return ["next"]

        if node.type_id == "set_stage":
            image_value = self._value_for(node, "image", None)
            stage_image = self._resolve_image_payload(image_value)
            self.outputs_cache[node.node_id] = {}
            self.log(stage_image)
            self.log("[Set Stage] Updated stage preview.")
            return ["next"]

        if node.type_id == "mouse_move":
            import pyautogui

            pyautogui.FAILSAFE = True
            x = int(self._value_for(node, "x", 0))
            y = int(self._value_for(node, "y", 0))
            duration_ms = max(0, int(self._value_for(node, "duration_ms", 0)))
            pyautogui.moveTo(x, y, duration=duration_ms / 1000)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Mouse Move] Cursor moved to ({x}, {y}).")
            return ["next"]

        if node.type_id == "mouse_click":
            import pyautogui

            pyautogui.FAILSAFE = True
            button = str(self._value_for(node, "button", "left"))
            clicks = max(1, int(self._value_for(node, "clicks", 1)))
            pyautogui.click(button=button, clicks=clicks)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Mouse Click] Clicked {button} {clicks} time(s).")
            return ["next"]

        if node.type_id == "hold_mouse":
            import pyautogui

            pyautogui.FAILSAFE = True
            button = str(self._value_for(node, "button", "left"))
            self._hold_mouse_button(pyautogui, button)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Hold Mouse] Holding {button}.")
            return ["next"]

        if node.type_id == "release_mouse":
            import pyautogui

            pyautogui.FAILSAFE = True
            button = str(self._value_for(node, "button", "left"))
            released = self._release_mouse_button(pyautogui, button)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Release Mouse] {'Released' if released else 'Skipped'} {button}.")
            return ["next"]

        if node.type_id == "press_key":
            import pyautogui

            pyautogui.FAILSAFE = True
            key = str(self._value_for(node, "key", "enter"))
            pyautogui.press(key)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Press Key] Pressed {key}.")
            return ["next"]

        if node.type_id == "press_key_combo":
            import pyautogui

            pyautogui.FAILSAFE = True
            keys = self._combo_keys_for(node)
            pyautogui.hotkey(*keys)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Press Key Combo] Pressed {' + '.join(keys)}.")
            return ["next"]

        if node.type_id == "hold_key":
            import pyautogui

            pyautogui.FAILSAFE = True
            key = str(self._value_for(node, "key", "shift"))
            self._hold_key(pyautogui, key)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Hold Key] Holding {key}.")
            return ["next"]

        if node.type_id == "release_key":
            import pyautogui

            pyautogui.FAILSAFE = True
            key = str(self._value_for(node, "key", "shift"))
            released = self._release_key(pyautogui, key)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Release Key] {'Released' if released else 'Skipped'} {key}.")
            return ["next"]

        if node.type_id == "type_text":
            import pyautogui

            pyautogui.FAILSAFE = True
            text = str(self._value_for(node, "text", ""))
            interval_ms = max(0, int(self._value_for(node, "interval_ms", 0)))
            pyautogui.write(text, interval=interval_ms / 1000)
            self.outputs_cache[node.node_id] = {}
            self.log(f"[Type Text] Typed {len(text)} character(s).")
            return ["next"]

        raise RuntimeError(f"Unsupported flow node: {definition.title}")

    def resolve_output(self, node_id: str, output_key: str) -> Any:
        node = self.nodes[node_id]
        definition = self.catalog[node.type_id]

        if definition.is_flow_node:
            if node_id not in self.outputs_cache:
                raise RuntimeError(
                    f"Node '{definition.title}' must run before its '{output_key}' output can be used."
                )
            return self.outputs_cache[node_id].get(output_key)

        if node_id not in self.pure_cache:
            self.pure_cache[node_id] = self._evaluate_pure_node(node, definition)
        return self.pure_cache[node_id].get(output_key)

    def _evaluate_pure_node(self, node: NodeModel, definition: NodeDefinition) -> dict[str, Any]:
        if self.should_stop():
            raise RuntimeError("Execution stopped.")

        if node.type_id == "number_value":
            return {"value": float(node.config.get("value", 0.0))}

        if node.type_id in {"text_value", "path_value"}:
            return {"value": str(node.config.get("value", ""))}

        if node.type_id == "boolean_value":
            return {"value": bool(node.config.get("value", False))}

        if node.type_id == "get_variable":
            name = self._normalize_variable_name(self._value_for(node, "name", ""))
            return {"value": self.variables.get(name, 0)}

        if node.type_id == "math_operation":
            left = float(self._value_for(node, "left", 0.0))
            right = float(self._value_for(node, "right", 0.0))
            operator = self._normalize_math_operator(node.config.get("operator", "+"))
            operations = {
                "+": left + right,
                "-": left - right,
                "*": left * right,
                "/": left / right if not math.isclose(right, 0.0) else 0.0,
            }
            return {"result": operations[operator]}

        if node.type_id == "compare_numbers":
            left = float(self._value_for(node, "left", 0.0))
            right = float(self._value_for(node, "right", 0.0))
            operator = self._normalize_compare_operator(node.config.get("operator", ">"))
            comparisons = {
                ">": left > right,
                ">=": left >= right,
                "=": math.isclose(left, right),
                "<=": left <= right,
                "<": left < right,
                "!=": not math.isclose(left, right),
            }
            return {"result": comparisons[operator]}

        if node.type_id == "join_text":
            first = str(self._value_for(node, "first", ""))
            second = str(self._value_for(node, "second", ""))
            separator = str(node.config.get("separator", " "))
            return {"result": f"{first}{separator}{second}"}

        if node.type_id == "replace_text":
            source = str(self._value_for(node, "source", ""))
            find = str(self._value_for(node, "find", ""))
            replace = str(self._value_for(node, "replace", ""))
            return {"result": source.replace(find, replace)}

        if node.type_id == "text_contains":
            source = str(self._value_for(node, "source", ""))
            search = str(self._value_for(node, "search", ""))
            return {"result": search in source}

        if node.type_id == "boolean_not":
            value = bool(self._value_for(node, "value", False))
            return {"result": not value}

        if node.type_id == "boolean_and":
            left = bool(self._value_for(node, "left", False))
            right = bool(self._value_for(node, "right", False))
            return {"result": left and right}

        if node.type_id == "boolean_or":
            left = bool(self._value_for(node, "left", False))
            right = bool(self._value_for(node, "right", False))
            return {"result": left or right}

        if node.type_id == "take_screenshot":
            import mss

            with mss.mss() as screen_capture:
                screenshot = screen_capture.grab(screen_capture.monitors[0])
            image_payload = self._image_payload_from_rgb(screenshot.rgb, screenshot.size)
            self.log("[Take Screenshot] Captured image in memory.")
            return {"image": image_payload}

        if node.type_id == "crop_image":
            from PIL import Image

            image_value = self._value_for(node, "image", None)
            image_bytes = self._resolve_image_data(image_value, "")
            x = int(self._value_for(node, "x", 0))
            y = int(self._value_for(node, "y", 0))
            width = max(1, int(self._value_for(node, "width", 1)))
            height = max(1, int(self._value_for(node, "height", 1)))
            with Image.open(io.BytesIO(image_bytes)) as image_file:
                image = image_file.convert("RGB")
                right = min(image.width, x + width)
                bottom = min(image.height, y + height)
                if x < 0 or y < 0 or x >= image.width or y >= image.height or right <= x or bottom <= y:
                    raise RuntimeError("Crop Image area must overlap the input image.")
                cropped = image.crop((x, y, right, bottom))
            return {"image": self._image_payload_from_pil(cropped)}

        if node.type_id == "set_image_pixel":
            from PIL import Image

            image_value = self._value_for(node, "image", None)
            image_bytes = self._resolve_image_data(image_value, "")
            x = int(self._value_for(node, "x", 0))
            y = int(self._value_for(node, "y", 0))
            red = max(0, min(255, int(self._value_for(node, "red", 0))))
            green = max(0, min(255, int(self._value_for(node, "green", 0))))
            blue = max(0, min(255, int(self._value_for(node, "blue", 0))))
            with Image.open(io.BytesIO(image_bytes)) as image_file:
                image = image_file.convert("RGB")
                if x < 0 or y < 0 or x >= image.width or y >= image.height:
                    raise RuntimeError(
                        f"Image pixel ({x}, {y}) is outside the image bounds {image.width}x{image.height}."
                    )
                updated = image.copy()
                updated.putpixel((x, y), (red, green, blue))
            return {"image": self._image_payload_from_pil(updated)}

        if node.type_id == "files_count":
            files = self._value_for(node, "files", [])
            return {"count": len(files or [])}

        if node.type_id == "first_file":
            files = self._value_for(node, "files", [])
            first = files[0] if files else ""
            return {"path": str(first)}

        if node.type_id == "file_exists":
            value = str(self._value_for(node, "path", ""))
            return {"exists": self._resolve_path(value).exists()}

        if node.type_id == "read_text_file":
            value = str(self._value_for(node, "path", ""))
            path = self._require_file(self._resolve_path(value))
            return {"text": path.read_text(encoding="utf-8")}

        if node.type_id == "path_join":
            folder = str(self._value_for(node, "folder", "."))
            name = str(self._value_for(node, "name", ""))
            return {"path": str(Path(folder) / name)}

        if node.type_id == "file_name":
            value = str(self._value_for(node, "path", ""))
            return {"name": Path(value).name}

        raise RuntimeError(f"Unsupported pure node: {definition.title}")

    def _walk_flow_output(self, node_id: str, output_key: str) -> None:
        for connection in self.outgoing_flow.get((node_id, output_key), []):
            self._walk(connection.to_node_id)

    def _value_for(self, node: NodeModel, port_key: str, fallback: Any) -> Any:
        incoming = self.incoming_data.get((node.node_id, port_key))
        if incoming is not None:
            return self.resolve_output(incoming.from_node_id, incoming.from_port_key)
        return node.config.get(port_key, fallback)

    def _resolve_path(self, path_value: str | Path) -> Path:
        text = str(path_value).replace("{project_dir}", str(self.base_dir)).replace(
            "{timestamp}", time.strftime("%Y%m%d_%H%M%S")
        )
        expanded = Path(text)
        if expanded.is_absolute():
            return expanded
        return (self.base_dir / expanded).resolve()

    def _prepare_output_file(self, raw_value: str) -> Path:
        return self._resolve_path(raw_value)

    def _resolve_image_source(self, image_value: Any, file_path_value: Any) -> Path:
        if isinstance(image_value, dict) and image_value.get("kind") == "image" and image_value.get("path"):
            image_path = self._resolve_path(str(image_value["path"]))
        elif isinstance(image_value, str) and image_value.strip():
            image_path = self._resolve_path(image_value)
        elif str(file_path_value).strip():
            image_path = self._resolve_path(str(file_path_value))
        else:
            raise RuntimeError("Connect an image or a file path before using Get Pixel from Image.")

        if not image_path.exists():
            raise RuntimeError(f"Image file not found: {image_path}")
        return image_path

    def _resolve_image_data(self, image_value: Any, file_path_value: Any) -> bytes:
        if isinstance(image_value, dict) and image_value.get("kind") == "image":
            if image_value.get("data_base64"):
                return base64.b64decode(str(image_value["data_base64"]))
            if image_value.get("path"):
                image_path = self._resolve_image_source(image_value, file_path_value)
                return image_path.read_bytes()

        image_path = self._resolve_image_source(image_value, file_path_value)
        return image_path.read_bytes()

    def _resolve_image_payload(self, image_value: Any) -> dict[str, str]:
        if isinstance(image_value, dict) and image_value.get("kind") == "stage_image":
            image_value = {key: value for key, value in image_value.items() if key != "kind"}
            image_value["kind"] = "image"
        if isinstance(image_value, dict) and image_value.get("kind") == "image":
            payload = dict(image_value)
            payload["kind"] = "stage_image"
            return payload
        if isinstance(image_value, str) and image_value.strip():
            image_path = self._resolve_path(image_value)
            data = image_path.read_bytes()
            payload = self._image_payload_from_bytes(data)
            payload["path"] = str(image_path.resolve())
            payload["kind"] = "stage_image"
            return payload
        raise RuntimeError("Connect an image before using Set Stage.")

    def _describe_image_source(self, image_value: Any, file_path_value: Any) -> str:
        if isinstance(image_value, dict) and image_value.get("kind") == "image":
            if image_value.get("path"):
                return str(self._resolve_path(str(image_value["path"])))
            if image_value.get("data_base64"):
                return "in-memory image"
        if isinstance(image_value, str) and image_value.strip():
            return str(self._resolve_path(image_value))
        if str(file_path_value).strip():
            return str(self._resolve_path(str(file_path_value)))
        return "in-memory image"

    def _pixel_outputs(self, x: int, y: int, red: int, green: int, blue: int) -> dict[str, Any]:
        pixel_value = {"r": red, "g": green, "b": blue, "x": x, "y": y}
        return {
            "pixel": pixel_value,
            "red": red,
            "green": green,
            "blue": blue,
        }

    def _sleep_with_stop(self, seconds: float) -> None:
        end_time = time.time() + max(0.0, seconds)
        while time.time() < end_time:
            if self.should_stop():
                raise RuntimeError("Execution stopped.")
            remaining = end_time - time.time()
            time.sleep(min(0.05, max(0.0, remaining)))

    def _normalize_math_operator(self, operator: Any) -> str:
        raw = str(operator)
        mapping = {
            "add": "+",
            "subtract": "-",
            "multiply": "*",
            "divide": "/",
        }
        if raw in {"+", "-", "*", "/"}:
            return raw
        return mapping.get(raw, "+")

    def _normalize_compare_operator(self, operator: Any) -> str:
        raw = str(operator)
        mapping = {
            "greater_than": ">",
            "less_than": "<",
            "equal": "=",
            "greater_or_equal": ">=",
            "less_or_equal": "<=",
            "not_equal": "!=",
        }
        if raw in {">", "<", "=", ">=", "<=", "!="}:
            return raw
        return mapping.get(raw, ">")

    def _append_text_file(self, path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def _normalize_variable_name(self, raw_name: Any) -> str:
        name = str(raw_name).strip()
        if not name:
            raise RuntimeError("Variable name cannot be empty.")
        return name

    def _coerce_variable_number(self, value: Any) -> float:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError as exc:
            raise RuntimeError(f"Variable '{value}' is not a number and cannot be changed.") from exc

    def _coerce_variable_storage_value(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else value
        text = str(value)
        stripped = text.strip()
        if not stripped:
            return text
        if re.fullmatch(r"[+-]?\d+", stripped):
            try:
                return int(stripped)
            except ValueError:
                return text
        if re.fullmatch(r"[+-]?(?:\d+\.\d+|\d+\.|\.\d+)", stripped):
            try:
                number = float(stripped)
                return int(number) if number.is_integer() else number
            except ValueError:
                return text
        return text

    def _format_variable_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _delete_file(self, path: Path, missing_ok: bool) -> bool:
        if not path.exists():
            if missing_ok:
                return False
            raise RuntimeError(f"File not found: {path}")
        if path.is_dir():
            raise RuntimeError(f"Delete File only supports files, not folders: {path}")
        path.unlink()
        return True

    def _require_file(self, path: Path) -> Path:
        if not path.exists():
            raise RuntimeError(f"File not found: {path}")
        if path.is_dir():
            raise RuntimeError(f"Expected a file but got a folder: {path}")
        return path

    def _prepare_destination_file(self, path: Path, overwrite: bool) -> None:
        if path.exists() and path.is_dir():
            raise RuntimeError(f"Destination must be a file path, not a folder: {path}")
        if path.exists() and not overwrite:
            raise RuntimeError(f"Destination file already exists: {path}")
        if path.exists() and overwrite:
            path.unlink()

    def _image_payload_from_rgb(self, rgb_bytes: bytes, size: Any) -> dict[str, str]:
        from PIL import Image

        width, height = int(size.width), int(size.height)
        image = Image.frombytes("RGB", (width, height), rgb_bytes)
        return self._image_payload_from_pil(image)

    def _image_payload_from_pil(self, image) -> dict[str, str]:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return self._image_payload_from_bytes(buffer.getvalue())

    def _image_payload_from_bytes(self, image_bytes: bytes) -> dict[str, str]:
        buffer = io.BytesIO()
        buffer.write(image_bytes)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return {
            "kind": "image",
            "data_base64": encoded,
        }

    def _combo_keys_for(self, node: NodeModel) -> list[str]:
        keys = [
            str(self._value_for(node, "modifier_1", "")).strip(),
            str(self._value_for(node, "modifier_2", "")).strip(),
            str(self._value_for(node, "key", "s")).strip(),
        ]
        normalized = [key for key in keys if key]
        if not normalized:
            raise RuntimeError("Press Key Combo needs at least one key.")
        deduped: list[str] = []
        for key in normalized:
            if key not in deduped:
                deduped.append(key)
        return deduped

    def _hold_key(self, pyautogui_module, key: str) -> None:
        normalized = key.strip()
        if not normalized:
            raise RuntimeError("Hold Key needs a key.")
        with _HELD_INPUTS_LOCK:
            if normalized in _HELD_KEYS:
                return
            pyautogui_module.keyDown(normalized)
            _HELD_KEYS.add(normalized)

    def _release_key(self, pyautogui_module, key: str) -> bool:
        normalized = key.strip()
        if not normalized:
            raise RuntimeError("Release Key needs a key.")
        with _HELD_INPUTS_LOCK:
            if normalized not in _HELD_KEYS:
                return False
            pyautogui_module.keyUp(normalized)
            _HELD_KEYS.remove(normalized)
            return True

    def _hold_mouse_button(self, pyautogui_module, button: str) -> None:
        normalized = button.strip().lower()
        if not normalized:
            raise RuntimeError("Hold Mouse needs a button.")
        with _HELD_INPUTS_LOCK:
            if normalized in _HELD_MOUSE_BUTTONS:
                return
            pyautogui_module.mouseDown(button=normalized)
            _HELD_MOUSE_BUTTONS.add(normalized)

    def _release_mouse_button(self, pyautogui_module, button: str) -> bool:
        normalized = button.strip().lower()
        if not normalized:
            raise RuntimeError("Release Mouse needs a button.")
        with _HELD_INPUTS_LOCK:
            if normalized not in _HELD_MOUSE_BUTTONS:
                return False
            pyautogui_module.mouseUp(button=normalized)
            _HELD_MOUSE_BUTTONS.remove(normalized)
            return True

    def _release_held_inputs(self) -> tuple[int, int]:
        with _HELD_INPUTS_LOCK:
            keys = list(_HELD_KEYS)
            _HELD_KEYS.clear()
            buttons = list(_HELD_MOUSE_BUTTONS)
            _HELD_MOUSE_BUTTONS.clear()
        if not keys and not buttons:
            return (0, 0)
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            for key in reversed(keys):
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    continue
            for button in reversed(buttons):
                try:
                    pyautogui.mouseUp(button=button)
                except Exception:
                    continue
        except Exception:
            return (len(keys), len(buttons))
        return (len(keys), len(buttons))
