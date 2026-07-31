"""ffprobe wrapper -> :class:`MediaInfo`.

Extracts exactly the properties the decision tree needs: codec, bit depth,
HDR-ness, variable frame rate, rotation, and basic audio info.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ffmpeg import run_ffprobe

# color_transfer values that indicate HDR.
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (Dolby Vision/HDR10), HLG

# 10-bit pixel formats we may encounter from iPhone HEVC.
_10BIT_MARKERS = ("p10", "p012", "p016", "10le", "10be")


@dataclass
class MediaInfo:
    path: Path
    video_codec: Optional[str]
    pix_fmt: Optional[str]
    bit_depth: int
    width: int
    height: int
    is_hdr: bool
    is_dolby_vision: bool
    is_vfr: bool
    rotation: int
    avg_frame_rate: float
    audio_codec: Optional[str]
    duration: float

    @property
    def needs_color_conversion(self) -> bool:
        """True when the source carries HDR color that must be tone-mapped."""
        return self.is_hdr


def _parse_rate(rate: Optional[str]) -> float:
    """Parse an ffprobe rational like '30000/1001' into a float."""
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _bit_depth(pix_fmt: Optional[str]) -> int:
    if not pix_fmt:
        return 8
    return 10 if any(m in pix_fmt for m in _10BIT_MARKERS) else 8


def _rotation(video_stream: dict) -> int:
    """Extract display rotation from side-data or tags, normalized to 0-359."""
    for side in video_stream.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                return int(round(float(side["rotation"]))) % 360
            except (ValueError, TypeError):
                pass
    tag = video_stream.get("tags", {}).get("rotate")
    if tag is not None:
        try:
            return int(tag) % 360
        except ValueError:
            pass
    return 0


def probe(path: Path) -> MediaInfo:
    """Probe ``path`` and return a :class:`MediaInfo`."""
    path = Path(path)
    raw = run_ffprobe(
        [
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    data = json.loads(raw)
    streams = data.get("streams", [])

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise ValueError(f"No video stream found in {path}")

    pix_fmt = video.get("pix_fmt")
    transfer = video.get("color_transfer")
    is_hdr = transfer in _HDR_TRANSFERS
    is_dv = any(
        "dv_profile" in (side or {})
        for side in video.get("side_data_list", []) or []
    )

    avg = _parse_rate(video.get("avg_frame_rate"))
    r_rate = _parse_rate(video.get("r_frame_rate"))
    # VFR heuristic: the average (real) rate differs from the base rate.
    is_vfr = bool(avg and r_rate and abs(avg - r_rate) > 0.01)

    duration = _parse_rate(data.get("format", {}).get("duration")) or 0.0
    if not duration:
        duration = _parse_rate(video.get("duration")) or 0.0

    return MediaInfo(
        path=path,
        video_codec=video.get("codec_name"),
        pix_fmt=pix_fmt,
        bit_depth=_bit_depth(pix_fmt),
        width=int(video.get("width", 0) or 0),
        height=int(video.get("height", 0) or 0),
        is_hdr=is_hdr,
        is_dolby_vision=is_dv,
        is_vfr=is_vfr,
        rotation=_rotation(video),
        avg_frame_rate=avg,
        audio_codec=audio.get("codec_name") if audio else None,
        duration=duration,
    )
