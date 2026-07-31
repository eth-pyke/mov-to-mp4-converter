"""Build and run the ffmpeg command for a :class:`ConversionPlan`.

The tone-mapping filter chain is chosen at runtime from whatever the installed
ffmpeg actually supports (libplacebo > zscale > colorspace fallback), so the
tool stays usable across the many different ffmpeg builds people have.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Callable, List, Optional

from .decisions import Action, ConversionPlan, OutputFormat
from .ffmpeg import find_binary, run_ffmpeg
from .probe import MediaInfo


class ToneMapUnsupported(RuntimeError):
    """Raised when HDR tone-mapping is required but no capable filter exists."""


@functools.lru_cache(maxsize=1)
def _available_filters() -> frozenset:
    """Return the set of filter names the installed ffmpeg exposes."""
    import subprocess

    ffmpeg = find_binary("ffmpeg")
    out = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
    ).stdout
    names = set()
    for line in out.splitlines():
        parts = line.split()
        # Lines look like: " T.. name  V->V  description"
        if len(parts) >= 2 and parts[0].isalpha() is False:
            names.add(parts[1])
    return frozenset(names)


def _tonemap_filters() -> List[str]:
    """Pick the best available HDR->SDR (Rec.709) filter chain.

    Returns a list of "-vf"-ready filter strings. Raises
    :class:`ToneMapUnsupported` when the ffmpeg build can't tone-map at all.
    """
    available = _available_filters()

    if "libplacebo" in available:
        # libplacebo does the whole HDR->SDR pipeline in one high-quality pass.
        return [
            "libplacebo=colorspace=bt709:color_primaries=bt709:"
            "color_trc=bt709:range=tv:tonemapping=bt.2390:format=yuv420p"
        ]

    if "zscale" in available:
        # Classic, reliable software tonemap: linearize -> tonemap -> Rec.709.
        return [
            "zscale=transfer=linear:npl=100",
            "format=gbrpf32le",
            "zscale=primaries=bt709",
            "tonemap=tonemap=hable:desat=0",
            "zscale=transfer=bt709:matrix=bt709:range=tv",
            "format=yuv420p",
        ]

    if "tonemap" in available and "colorspace" in available:
        # Best-effort fallback for stripped builds: no true linear-light stage,
        # so quality is lower, but it still corrects the washed-out look.
        return [
            "colorspace=all=bt709:iall=bt2020nc:fast=1",
            "tonemap=tonemap=hable:desat=0",
            "format=yuv420p",
        ]

    raise ToneMapUnsupported(
        "This ffmpeg build has no HDR tone-mapping filter (need libplacebo or "
        "zscale). Reinstall a fuller ffmpeg, e.g.:\n"
        "  brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg\n"
        "or pass --hdr to preserve HDR without tone-mapping."
    )


def _video_encoder_args(plan: ConversionPlan) -> List[str]:
    if plan.output_format is OutputFormat.PRORES_MOV:
        # ProRes 422 HQ, edit-ideal intra-frame codec (future --prores mode).
        return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]

    # MP4 / H.264
    args = ["-c:v", "libx264", "-crf", str(plan.crf), "-preset", plan.preset]
    if plan.preserve_hdr:
        # Keep 10-bit and carry the HDR color tags through untouched.
        args += [
            "-profile:v", "high10",
            "-pix_fmt", "yuv420p10le",
            "-color_primaries", "bt2020",
            "-color_trc", "smpte2084",
            "-colorspace", "bt2020nc",
        ]
    else:
        args += [
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-colorspace", "bt709",
        ]
    return args


def build_command(info: MediaInfo, plan: ConversionPlan, output: Path) -> List[str]:
    """Build the ffmpeg argument list (excluding the binary itself)."""
    args: List[str] = ["-hide_banner", "-y", "-i", str(info.path)]

    # Progress on stdout so the runner can report a percentage.
    args += ["-progress", "pipe:1", "-nostats"]

    # Map video + optional audio; "?" makes the audio map non-fatal if absent.
    args += ["-map", "0:v:0"]
    if plan.has_audio:
        args += ["-map", "0:a:0?"]

    if plan.action is Action.REMUX:
        # `-c copy` copies every mapped stream (video + audio) losslessly.
        args += ["-c", "copy"]
    else:
        if plan.tone_map:
            args += ["-vf", ",".join(_tonemap_filters())]
        args += _video_encoder_args(plan)
        if plan.force_cfr and info.avg_frame_rate:
            # Normalize VFR to a constant rate for clean edit-timeline sync.
            args += ["-fps_mode", "cfr", "-r", f"{info.avg_frame_rate:.5f}"]
        if plan.has_audio:
            args += ["-c:a", "copy"] if plan.audio_copy else ["-c:a", "aac", "-b:a", "256k"]

    args += ["-movflags", "+faststart", str(output)]
    return args


def convert(
    info: MediaInfo,
    plan: ConversionPlan,
    output: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> Path:
    """Execute the conversion described by ``plan``; return the output path."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    args = build_command(info, plan, output)
    run_ffmpeg(args, duration=info.duration or None, on_progress=on_progress)
    return output
