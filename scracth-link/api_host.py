import argparse
import base64
import os
import shutil
import subprocess
import threading
import time
from contextlib import suppress
from typing import Any

import mss
import mss.tools
import pyautogui
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

HERE = os.path.dirname(os.path.abspath(__file__))
EXTENSION_FILE = os.path.join(HERE, "flowmacro_penguinmod.js")

MOUSE_BUTTONS = {"left", "middle", "right"}


class MouseMoveRequest(BaseModel):
    x: int
    y: int
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


app = FastAPI(title="FlowMacro Scratch Link")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_button(button: str) -> str:
    button = button.lower().strip()
    if button not in MOUSE_BUTTONS:
        raise HTTPException(status_code=400, detail=f"Unsupported mouse button: {button}")
    return button


def screenshot_as_base64() -> dict[str, Any]:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
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


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "FlowMacro Scratch Link",
        "status": "ok",
        "extensionUrl": "/extension.js",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    width, height = pyautogui.size()
    x, y = pyautogui.position()
    return {
        "ok": True,
        "screen": {"width": width, "height": height},
        "mouse": {"x": x, "y": y},
    }


@app.get("/extension.js")
def extension_js() -> FileResponse:
    return FileResponse(EXTENSION_FILE, media_type="application/javascript")


@app.get("/screen")
def get_screen() -> dict[str, Any]:
    return screenshot_as_base64()


@app.get("/screen/info")
def get_screen_info() -> dict[str, Any]:
    width, height = pyautogui.size()
    return {"width": width, "height": height}


@app.get("/mouse")
def get_mouse() -> dict[str, Any]:
    x, y = pyautogui.position()
    return {"x": x, "y": y}


@app.post("/mouse/move")
def move_mouse(payload: MouseMoveRequest) -> dict[str, Any]:
    pyautogui.moveTo(payload.x, payload.y, duration=max(payload.duration, 0))
    x, y = pyautogui.position()
    return {"ok": True, "x": x, "y": y}


@app.post("/mouse/down")
def mouse_down(payload: MouseButtonRequest) -> dict[str, Any]:
    pyautogui.mouseDown(button=normalize_button(payload.button))
    return {"ok": True}


@app.post("/mouse/up")
def mouse_up(payload: MouseButtonRequest) -> dict[str, Any]:
    pyautogui.mouseUp(button=normalize_button(payload.button))
    return {"ok": True}


@app.post("/mouse/click")
def mouse_click(payload: MouseClickRequest) -> dict[str, Any]:
    pyautogui.click(
        button=normalize_button(payload.button),
        clicks=max(payload.clicks, 1),
        interval=max(payload.interval, 0),
    )
    return {"ok": True}


@app.post("/keyboard/down")
def key_down(payload: KeyRequest) -> dict[str, Any]:
    pyautogui.keyDown(payload.key)
    return {"ok": True}


@app.post("/keyboard/up")
def key_up(payload: KeyRequest) -> dict[str, Any]:
    pyautogui.keyUp(payload.key)
    return {"ok": True}


@app.post("/keyboard/press")
def key_press(payload: KeyRequest) -> dict[str, Any]:
    pyautogui.press(payload.key)
    return {"ok": True}


@app.post("/keyboard/hotkey")
def hotkey(payload: HotkeyRequest) -> dict[str, Any]:
    if not payload.keys:
        raise HTTPException(status_code=400, detail="At least one key is required")
    pyautogui.hotkey(*payload.keys)
    return {"ok": True}


@app.post("/keyboard/write")
def write_text(payload: WriteRequest) -> dict[str, Any]:
    pyautogui.write(payload.text, interval=max(payload.interval, 0))
    return {"ok": True}


@app.post("/wait")
def wait_seconds(payload: WaitRequest) -> dict[str, Any]:
    time.sleep(max(payload.seconds, 0))
    return {"ok": True}


def open_cloudflare_tunnel(port: int) -> str | None:
    cloudflared = shutil.which("cloudflared")
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
            print(f"[cloudflared] {line.rstrip()}")
            if "trycloudflare.com" in line and "https://" in line and not url_holder["url"]:
                for token in line.split():
                    if token.startswith("https://") and "trycloudflare.com" in token:
                        url_holder["url"] = token
                        break

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


def main() -> None:
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

    public_url = None
    if args.tunnel == "cloudflare":
        public_url = start_tunnel(args.port)

    print(f"Local API: http://{args.host}:{args.port}")
    print(f"Extension URL: http://{args.host}:{args.port}/extension.js")
    if public_url:
        print(f"Public API: {public_url}")
        print(f"Public extension URL: {public_url}/extension.js")
    else:
        print("No public tunnel could be opened. The local server will still start.")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
