# FlowMacro

FlowMacro is a platform for building desktop automation with node blocks.

## FlowMacro Studio

`FlowMacro Studio` is the Python desktop app in this repo. It gives you:

- A draggable node workspace with typed in/out ports
- Red top-banner errors when you try to connect mismatched port types
- Blocks for screenshots, pixel reads, files, keyboard, mouse, logic, and control flow
- Save/load as `.fmp` files using the `FlowMacroProject` format

## Run It

1. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

2. Start the studio:

```powershell
python main.py
```

3. Open an existing project:

```powershell
python main.py path\to\project.fmp
```

## Notes

- The app ships with a starter workspace so you can immediately test the editor.
- Delete selected nodes or wires with `Delete` or `Backspace`.
- Mouse wheel zooms, and middle mouse button pans the workspace.
