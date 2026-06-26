from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class FileOpenError(RuntimeError):
    pass


def open_local_file(path: Path) -> None:
    if not path.exists():
        raise FileOpenError(f"File not found: {path}")

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return

    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
        return

    subprocess.Popen(["xdg-open", str(path)])
