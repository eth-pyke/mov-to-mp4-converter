"""Turn a :class:`~converter.probe.MediaInfo` + user :class:`Options` into a
codec-agnostic :class:`ConversionPlan`.

This module holds all the "what should we do" logic and no ffmpeg specifics, so
the same decisions drive the CLI today and a GUI (or ProRes mode) later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .probe import MediaInfo


class OutputFormat(Enum):
    """Supported output targets. ProRes is wired in but not yet CLI-exposed."""

    MP4_H264 = "mp4_h264"
    PRORES_MOV = "prores_mov"

    @property
    def extension(self) -> str:
        return ".mov" if self is OutputFormat.PRORES_MOV else ".mp4"


class Action(Enum):
    """The two top-level strategies."""

    REMUX = "remux"        # stream-copy, lossless, instant
    REENCODE = "reencode"  # decode + re-encode (needed for HDR/HEVC/etc.)


@dataclass
class Options:
    """User-facing knobs. A GUI would populate the same object."""

    output_format: OutputFormat = OutputFormat.MP4_H264
    preserve_hdr: bool = False      # --hdr: keep 10-bit HDR instead of tone-mapping
    force_cfr: bool = False         # --cfr: normalize VFR to constant frame rate
    force_reencode: bool = False    # --force-reencode: never remux
    crf: int = 18                   # x264 quality (lower = better)
    preset: str = "slow"            # x264 speed/quality tradeoff
    overwrite: bool = False


@dataclass
class ConversionPlan:
    """The concrete recipe convert.py turns into an ffmpeg command."""

    action: Action
    output_format: OutputFormat
    tone_map: bool          # HDR -> SDR Rec.709
    preserve_hdr: bool      # keep 10-bit HDR color
    force_cfr: bool
    crf: int
    preset: str
    audio_copy: bool        # copy the source audio stream vs re-encode to AAC
    has_audio: bool

    @property
    def summary(self) -> str:
        if self.action is Action.REMUX:
            return "remux (stream copy, lossless)"
        bits = []
        if self.tone_map:
            bits.append("tone-map HDR->SDR")
        elif self.preserve_hdr:
            bits.append("preserve HDR 10-bit")
        if self.force_cfr:
            bits.append("VFR->CFR")
        detail = ", ".join(bits) if bits else "SDR"
        return f"re-encode {self.output_format.value} ({detail})"


def _remux_eligible(info: MediaInfo, options: Options) -> bool:
    """A source can be losslessly remuxed only when nothing needs processing."""
    return (
        options.output_format is OutputFormat.MP4_H264
        and not options.force_reencode
        and not options.preserve_hdr
        and not options.force_cfr
        and info.video_codec == "h264"
        and info.bit_depth == 8
        and not info.is_hdr
    )


def plan_conversion(info: MediaInfo, options: Options) -> ConversionPlan:
    """Decide how to convert ``info`` given ``options``."""
    has_audio = info.audio_codec is not None
    # AAC copies straight into both mp4 and mov; anything else we re-encode.
    audio_copy = info.audio_codec == "aac"

    if _remux_eligible(info, options):
        return ConversionPlan(
            action=Action.REMUX,
            output_format=options.output_format,
            tone_map=False,
            preserve_hdr=False,
            force_cfr=False,
            crf=options.crf,
            preset=options.preset,
            audio_copy=audio_copy,
            has_audio=has_audio,
        )

    tone_map = info.is_hdr and not options.preserve_hdr
    preserve_hdr = info.is_hdr and options.preserve_hdr

    return ConversionPlan(
        action=Action.REENCODE,
        output_format=options.output_format,
        tone_map=tone_map,
        preserve_hdr=preserve_hdr,
        force_cfr=options.force_cfr,
        crf=options.crf,
        preset=options.preset,
        audio_copy=audio_copy,
        has_audio=has_audio,
    )
