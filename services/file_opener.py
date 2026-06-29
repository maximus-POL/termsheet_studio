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

    resolved_path = path.resolve()

    if sys.platform == "darwin":
        open_with_macos(resolved_path)
        return

    if sys.platform.startswith("win"):
        os.startfile(resolved_path)  # type: ignore[attr-defined]
        return

    subprocess.run(["xdg-open", str(resolved_path)], check=True)


def open_with_macos(path: Path) -> None:
    commands = (
        ["open", "-a", "Microsoft Excel", str(path)],
        ["open", str(path)],
    )
    errors: list[str] = []

    for command in commands:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or str(exc)).strip()
            errors.append(f"{' '.join(command)} -> {message}")

    raise FileOpenError("; ".join(errors) or f"Could not open file: {path}")
