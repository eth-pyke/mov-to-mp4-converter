"""HEIC/HEIF -> JPG conversion via macOS's built-in `sips` tool.

Kept separate from the video pipeline (probe/decisions/convert): image
conversion here is a direct format conversion with no HDR/VFR-style
decision-making, so it doesn't need the ConversionPlan machinery.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

EXTENSIONS = (".heic", ".heif")


class SipsNotFound(RuntimeError):
    """Raised when the `sips` binary isn't available (macOS-only tool)."""


def ensure_available() -> None:
    if shutil.which("sips") is None:
        raise SipsNotFound(
            "'sips' was not found on your PATH. HEIC conversion uses "
            "macOS's built-in image tool, so it's only available on macOS."
        )


def convert_heic_to_jpg(src: Path, output: Path, quality: int = 90) -> Path:
    """Convert a single HEIC/HEIF file to JPG. Returns the output path."""
    ensure_available()
    src, output = Path(src), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "sips",
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(quality),
            str(src),
            "--out", str(output),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sips failed: {(result.stderr or result.stdout).strip()}")
    return output
