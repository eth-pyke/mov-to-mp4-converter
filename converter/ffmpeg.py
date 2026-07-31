"""Locating and running the ffmpeg / ffprobe binaries.

Keeps every subprocess concern in one place so the rest of the core never has
to think about where the binaries live or how to stream progress.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, List, Optional


class FFmpegNotFound(RuntimeError):
    """Raised when ffmpeg or ffprobe cannot be located on PATH."""


def find_binary(name: str) -> str:
    """Return the absolute path to ``name`` or raise :class:`FFmpegNotFound`."""
    path = shutil.which(name)
    if not path:
        raise FFmpegNotFound(
            f"{name!r} was not found on your PATH.\n"
            f"Install it with:  brew install ffmpeg"
        )
    return path


def ensure_available() -> None:
    """Verify both ffmpeg and ffprobe are installed; raise otherwise."""
    find_binary("ffmpeg")
    find_binary("ffprobe")


def run_ffprobe(args: List[str]) -> str:
    """Run ffprobe with ``args`` and return stdout, raising on failure."""
    ffprobe = find_binary("ffprobe")
    result = subprocess.run(
        [ffprobe, *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return result.stdout


def run_ffmpeg(
    args: List[str],
    duration: Optional[float] = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> None:
    """Run ffmpeg with ``args``.

    When ``duration`` (seconds) and ``on_progress`` are supplied, ``-progress``
    output is parsed and ``on_progress`` is called with a 0.0-1.0 fraction. The
    caller is responsible for putting ``-progress pipe:1 -nostats`` in ``args``.
    """
    ffmpeg = find_binary("ffmpeg")
    proc = subprocess.Popen(
        [ffmpeg, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    if on_progress and duration and proc.stdout is not None:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                raw = line.split("=", 1)[1]
                # ffmpeg emits "N/A" until the first frame is processed.
                if raw.isdigit():
                    fraction = min(int(raw) / 1_000_000.0 / duration, 1.0)
                    on_progress(fraction)
            elif line == "progress=end":
                on_progress(1.0)

    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{stderr.strip()}")
