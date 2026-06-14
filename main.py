from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer

from flowmacro_studio.main_window import MainWindow, create_application


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FlowMacro Studio")
    parser.add_argument("project", nargs="?", help="Optional .fmp project to open.")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Start the UI offscreen and exit immediately for verification.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = create_application()
    project_path = Path(args.project).resolve() if args.project else None
    window = MainWindow(project_path=project_path)
    window.show()

    if args.smoke_test:
        QTimer.singleShot(0, window.close)
        QTimer.singleShot(0, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
