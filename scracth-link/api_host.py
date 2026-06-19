import argparse
import base64
import os
import platform
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import suppress
from typing import Any

import mss
import mss.tools
import pyautogui
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION_FILE = os.path.join(HERE, "flowmacro_penguinmod.js")
SESSION_ID = uuid.uuid4().hex
EXTENSION_TEMPLATE = ""

MOUSE_BUTTONS = {"left", "middle", "right"}
KEY_ALIASES = {
    "windows": "win",
    "meta": "win",
    "super": "win",
    "command": "command",
    "cmd": "command",
}


class MouseMoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0


class MouseOffsetRequest(BaseModel):
    dx: int
    dy: int
    duration: float = 0


class MouseButtonRequest(BaseModel):
    button: str = "left"


class MouseClickRequest(BaseModel):
    button: str = "left"
    clicks: int = 1
    interval: float = 0


class KeyRequest(BaseModel):
    key: str


class HotkeyRequest(BaseModel):
    keys: list[str] = Field(default_factory=list)


class WriteRequest(BaseModel):
    text: str
    interval: float = 0


class WaitRequest(BaseModel):
    seconds: float = 0.1


class ActionItem(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchRequest(BaseModel):
    actions: list[ActionItem] = Field(default_factory=list)


app = FastAPI(title="FlowMacro Scratch Link")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_extension_template() -> str:
    with open(EXTENSION_FILE, "r", encoding="utf-8") as handle:
        return handle.read()


def build_extension_script(base_url: str) -> str:
    return (
        EXTENSION_TEMPLATE
        .replace("__FLOWMACRO_SESSION_ID__", SESSION_ID)
        .replace("__FLOWMACRO_BASE_URL__", base_url.rstrip("/"))
    )


def require_session(x_flowmacro_session: str | None = Header(default=None)) -> None:
    if x_flowmacro_session != SESSION_ID:
        raise HTTPException(status_code=403, detail="Invalid FlowMacro session")


def normalize_button(button: str) -> str:
    button = button.lower().strip()
    if button not in MOUSE_BUTTONS:
        raise HTTPException(status_code=400, detail=f"Unsupported mouse button: {button}")
    return button


def normalize_key(key: str) -> str:
    return KEY_ALIASES.get(key.lower().strip(), key.lower().strip())


def capture_monitor(monitor: dict[str, int]) -> dict[str, Any]:
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        raw = mss.tools.to_png(shot.rgb, shot.size)
        encoded = base64.b64encode(raw).decode("ascii")
        return {
            "width": shot.width,
            "height": shot.height,
            "monitor": {
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"],
            },
            "imageBase64": encoded,
        }


def screenshot_as_base64(screen_number: int | None = None) -> dict[str, Any]:
    with mss.mss() as sct:
        monitors = sct.monitors
        if screen_number is None:
            monitor = monitors[0]
        else:
            if screen_number < 1 or screen_number >= len(monitors):
                raise HTTPException(
                    status_code=400,
                    detail=f"Screen {screen_number} is unavailable. Valid screens: 1-{len(monitors) - 1}",
                )
            monitor = monitors[screen_number]
    return capture_monitor(monitor)


def get_monitor_info(screen_number: int) -> dict[str, int]:
    with mss.mss() as sct:
        monitors = sct.monitors
        if screen_number < 1 or screen_number >= len(monitors):
            raise HTTPException(
                status_code=400,
                detail=f"Screen {screen_number} is unavailable. Valid screens: 1-{len(monitors) - 1}",
            )
        monitor = monitors[screen_number]
        return {
            "left": monitor["left"],
            "top": monitor["top"],
            "width": monitor["width"],
            "height": monitor["height"],
        }


def execute_action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action_type == "mouse.move":
        x = int(payload.get("x", 0))
        y = int(payload.get("y", 0))
        duration = max(float(payload.get("duration", 0)), 0)
        pyautogui.moveTo(x, y, duration=duration)
        x, y = pyautogui.position()
        return {"ok": True, "x": x, "y": y}

    if action_type == "mouse.moveBy":
        dx = int(payload.get("dx", 0))
        dy = int(payload.get("dy", 0))
        duration = max(float(payload.get("duration", 0)), 0)
        pyautogui.move(dx, dy, duration=duration)
        x, y = pyautogui.position()
        return {"ok": True, "x": x, "y": y}

    if action_type == "mouse.down":
        pyautogui.mouseDown(button=normalize_button(str(payload.get("button", "left"))))
        return {"ok": True}

    if action_type == "mouse.up":
        pyautogui.mouseUp(button=normalize_button(str(payload.get("button", "left"))))
        return {"ok": True}

    if action_type == "mouse.click":
        pyautogui.click(
            button=normalize_button(str(payload.get("button", "left"))),
            clicks=max(int(payload.get("clicks", 1)), 1),
            interval=max(float(payload.get("interval", 0)), 0),
        )
        return {"ok": True}

    if action_type == "keyboard.down":
        pyautogui.keyDown(normalize_key(str(payload.get("key", ""))))
        return {"ok": True}

    if action_type == "keyboard.up":
        pyautogui.keyUp(normalize_key(str(payload.get("key", ""))))
        return {"ok": True}

    if action_type == "keyboard.press":
        pyautogui.press(normalize_key(str(payload.get("key", ""))))
        return {"ok": True}

    if action_type == "keyboard.hotkey":
        keys = [normalize_key(str(key)) for key in payload.get("keys", [])]
        if not keys:
            raise HTTPException(status_code=400, detail="At least one key is required")
        pyautogui.hotkey(*keys)
        return {"ok": True}

    if action_type == "keyboard.write":
        pyautogui.write(str(payload.get("text", "")), interval=max(float(payload.get("interval", 0)), 0))
        return {"ok": True}

    if action_type == "wait":
        time.sleep(max(float(payload.get("seconds", 0)), 0))
        return {"ok": True}

    raise HTTPException(status_code=400, detail=f"Unsupported buffered action: {action_type}")


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "FlowMacro Scratch Link",
        "status": "ok",
        "sessionId": SESSION_ID,
        "extensionUrl": f"/extension/{SESSION_ID}.js",
        "docs": "/docs",
    }


@app.get("/health")
def health(x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    width, height = pyautogui.size()
    x, y = pyautogui.position()
    return {
        "ok": True,
        "screen": {"width": width, "height": height},
        "mouse": {"x": x, "y": y},
    }


@app.get("/extension/{session_id}.js")
def extension_js(session_id: str, request: Request) -> PlainTextResponse:
    if session_id != SESSION_ID:
        raise HTTPException(status_code=404, detail="Unknown extension session")
    base_url = str(request.base_url).rstrip("/")
    script = build_extension_script(base_url)
    return PlainTextResponse(script, media_type="application/javascript")


@app.get("/screen")
def get_screen(x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return screenshot_as_base64()


@app.get("/screen/all")
def get_all_screens(x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return screenshot_as_base64()


@app.get("/screen/{screen_number}")
def get_screen_number(screen_number: int, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return screenshot_as_base64(screen_number)


@app.get("/screen/info")
def get_screen_info(x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    width, height = pyautogui.size()
    return {"width": width, "height": height}


@app.get("/screen/info/{screen_number}")
def get_screen_number_info(screen_number: int, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return get_monitor_info(screen_number)


@app.get("/mouse")
def get_mouse(x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    x, y = pyautogui.position()
    return {"x": x, "y": y}


@app.post("/mouse/move")
def move_mouse(payload: MouseMoveRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    pyautogui.moveTo(payload.x, payload.y, duration=max(payload.duration, 0))
    x, y = pyautogui.position()
    return {"ok": True, "x": x, "y": y}


@app.post("/mouse/move-by")
def move_mouse_by(payload: MouseOffsetRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    pyautogui.move(payload.dx, payload.dy, duration=max(payload.duration, 0))
    x, y = pyautogui.position()
    return {"ok": True, "x": x, "y": y}


@app.post("/mouse/down")
def mouse_down(payload: MouseButtonRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    pyautogui.mouseDown(button=normalize_button(payload.button))
    return {"ok": True}


@app.post("/mouse/up")
def mouse_up(payload: MouseButtonRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    pyautogui.mouseUp(button=normalize_button(payload.button))
    return {"ok": True}


@app.post("/mouse/click")
def mouse_click(payload: MouseClickRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action(
        "mouse.click",
        {"button": payload.button, "clicks": payload.clicks, "interval": payload.interval},
    )


@app.post("/keyboard/down")
def key_down(payload: KeyRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("keyboard.down", {"key": payload.key})


@app.post("/keyboard/up")
def key_up(payload: KeyRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("keyboard.up", {"key": payload.key})


@app.post("/keyboard/press")
def key_press(payload: KeyRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("keyboard.press", {"key": payload.key})


@app.post("/keyboard/hotkey")
def hotkey(payload: HotkeyRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("keyboard.hotkey", {"keys": payload.keys})


@app.post("/keyboard/write")
def write_text(payload: WriteRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("keyboard.write", {"text": payload.text, "interval": payload.interval})


@app.post("/wait")
def wait_seconds(payload: WaitRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    return execute_action("wait", {"seconds": payload.seconds})


@app.post("/batch")
def run_batch(payload: BatchRequest, x_flowmacro_session: str | None = Header(default=None)) -> dict[str, Any]:
    require_session(x_flowmacro_session)
    results = [execute_action(action.type, action.payload) for action in payload.actions]
    return {"ok": True, "count": len(results), "results": results}


def open_cloudflare_tunnel(port: int) -> str | None:
    cloudflared = ensure_cloudflared()
    if not cloudflared:
        return None

    command = [cloudflared, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    url_holder = {"url": None}

    def collect() -> None:
        if not process.stdout:
            return
        for line in process.stdout:
            text = line.rstrip()
            if "trycloudflare.com" in text and "https://" in text and not url_holder["url"]:
                for token in line.split():
                    if token.startswith("https://") and "trycloudflare.com" in token:
                        url_holder["url"] = token
                        print(f"Cloudflare tunnel ready: {token}")
                        break
                continue

            lowered = text.lower()
            if any(word in lowered for word in ("error", "failed", "unable", "panic")):
                print(f"[cloudflared] {text}")

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()

    for _ in range(60):
        if url_holder["url"]:
            return url_holder["url"]
        if process.poll() is not None:
            break
        time.sleep(0.5)

    with suppress(Exception):
        process.terminate()
    return None


def start_tunnel(port: int) -> str | None:
    return open_cloudflare_tunnel(port)


def find_cloudflared_executable() -> str | None:
    cloudflared = shutil.which("cloudflared")
    if cloudflared:
        return cloudflared

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")

    candidates = [
        os.path.join(local_appdata, "Microsoft", "WinGet", "Packages"),
        os.path.join(program_files, "cloudflared"),
        os.path.join(program_files_x86, "cloudflared"),
        os.path.join(program_files, "Cloudflare", "Cloudflared"),
        os.path.join(program_files_x86, "Cloudflare", "Cloudflared"),
    ]

    for base in candidates:
        if not base or not os.path.isdir(base):
            continue

        direct = os.path.join(base, "cloudflared.exe")
        if os.path.isfile(direct):
            return direct

        for root, _, files in os.walk(base):
            if "cloudflared.exe" in files:
                return os.path.join(root, "cloudflared.exe")

    return None


def install_cloudflared_windows() -> str | None:
    winget = shutil.which("winget")
    if not winget:
        print("cloudflared was not found and winget is unavailable, so auto-install could not run.")
        return None

    print("cloudflared was not found. Attempting automatic install with winget...")
    command = [
        winget,
        "install",
        "--id",
        "Cloudflare.cloudflared",
        "--exact",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]

    try:
        result = subprocess.run(command, check=False, text=True)
    except OSError as exc:
        print(f"Automatic cloudflared install failed to launch: {exc}")
        return None

    if result.returncode != 0:
        existing = find_cloudflared_executable()
        if existing:
            print("winget reported a non-success code, but cloudflared was found locally and will be used.")
            return existing
        print(f"Automatic cloudflared install failed with exit code {result.returncode}.")
        return None

    return find_cloudflared_executable()


def ensure_cloudflared() -> str | None:
    cloudflared = find_cloudflared_executable()
    if cloudflared:
        return cloudflared

    if platform.system() == "Windows":
        return install_cloudflared_windows()

    print("cloudflared was not found on PATH.")
    return None


def main() -> None:
    global EXTENSION_TEMPLATE

    parser = argparse.ArgumentParser(description="Host a local API for the PenguinMod extension.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--tunnel",
        choices=["cloudflare", "none"],
        default="cloudflare",
        help="Expose the local API over Cloudflare Tunnel if possible.",
    )
    args = parser.parse_args()
    EXTENSION_TEMPLATE = load_extension_template()

    public_url = None
    if args.tunnel == "cloudflare":
        public_url = start_tunnel(args.port)

    local_base_url = f"http://{args.host}:{args.port}"
    local_extension_url = f"{local_base_url}/extension/{SESSION_ID}.js"

    print(f"Local API: {local_base_url}")
    print(f"Session ID: {SESSION_ID}")
    print(f"Extension URL: {local_extension_url}")
    if public_url:
        print(f"Public API: {public_url}")
        print(f"Public extension URL: {public_url}/extension/{SESSION_ID}.js")
    else:
        print("No public tunnel could be opened. The local server will still start.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
