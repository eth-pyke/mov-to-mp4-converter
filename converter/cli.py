"""Command-line interface. This is the only module that knows about argv,
printing, and batching -- all real work lives in the reusable core.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from .convert import ToneMapUnsupported, build_command, convert
from .decisions import Options, OutputFormat, plan_conversion
from .ffmpeg import FFmpegNotFound, ensure_available as ensure_ffmpeg, find_binary
from .heic import EXTENSIONS as HEIC_EXTENSIONS
from .heic import SipsNotFound, convert_heic_to_jpg
from .heic import ensure_available as ensure_sips
from .probe import probe

_VIDEO_EXTS = {".mov"}
_IMAGE_EXTS = set(HEIC_EXTENSIONS)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="convert.py",
        description="Convert iPhone .mov files to edit-ready .mp4 "
        "(quality-preserving, HDR-aware), and .heic photos to .jpg.",
    )
    p.add_argument(
        "input", type=Path,
        help="A .mov/.heic file, or a folder containing .mov and/or .heic files",
    )
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output file (single input) or output directory (folder input). "
        "Defaults to alongside each input.",
    )
    p.add_argument(
        "--hdr", action="store_true",
        help="Preserve HDR 10-bit instead of tone-mapping to SDR Rec.709.",
    )
    p.add_argument(
        "--cfr", action="store_true",
        help="Normalize variable frame rate to constant (better edit sync).",
    )
    p.add_argument("--crf", type=int, default=18, help="x264 quality, lower=better (default 18).")
    p.add_argument("--preset", default="slow", help="x264 preset (default slow).")
    p.add_argument(
        "--force-reencode", action="store_true",
        help="Always re-encode, even when a lossless remux would be possible.",
    )
    p.add_argument(
        "--prores", action="store_true",
        help="[experimental] Output ProRes 422 HQ .mov (edit-ideal) instead of MP4.",
    )
    p.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing output files.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Show the plan and ffmpeg command for each file without running.",
    )
    p.add_argument(
        "--jpg-quality", type=int, default=90,
        help="JPEG quality 0-100 for HEIC->JPG conversion (default 90).",
    )
    return p


def _gather_inputs(inp: Path) -> List[Path]:
    if inp.is_dir():
        files = sorted(
            f for f in inp.iterdir()
            if f.is_file() and f.suffix.lower() in _VIDEO_EXTS | _IMAGE_EXTS
        )
        return files
    if inp.is_file():
        return [inp]
    raise FileNotFoundError(f"Input not found: {inp}")


def _resolve_output(src: Path, args, ext: str, is_batch: bool) -> Path:
    if args.output is None:
        return src.with_suffix(ext)
    if is_batch or args.output.is_dir():
        # Treat --output as a directory in batch mode.
        return args.output / (src.stem + ext)
    return args.output


def _options_from_args(args) -> Options:
    return Options(
        output_format=OutputFormat.PRORES_MOV if args.prores else OutputFormat.MP4_H264,
        preserve_hdr=args.hdr,
        force_cfr=args.cfr,
        force_reencode=args.force_reencode,
        crf=args.crf,
        preset=args.preset,
        overwrite=args.overwrite,
    )


def _process(src: Path, args, options: Options, is_batch: bool) -> bool:
    """Convert one file. Return True on success (or dry-run), False on skip/error."""
    try:
        info = probe(src)
    except Exception as exc:  # noqa: BLE001 - report and continue the batch
        print(f"  ! {src.name}: could not probe ({exc})", file=sys.stderr)
        return False

    plan = plan_conversion(info, options)
    output = _resolve_output(src, args, options.output_format.extension, is_batch)

    if output.resolve() == src.resolve():
        print(f"  ! {src.name}: output would overwrite the source; skipping", file=sys.stderr)
        return False

    src_desc = (
        f"{info.video_codec} {info.bit_depth}-bit"
        f"{' HDR' if info.is_hdr else ''}"
        f"{' Dolby Vision' if info.is_dolby_vision else ''}"
        f"{' VFR' if info.is_vfr else ''}"
    )
    print(f"  {src.name}  [{src_desc}]  ->  {plan.summary}")

    if info.is_vfr and not options.force_cfr and plan.action.name != "REMUX":
        print("      note: source is VFR; pass --cfr for cleaner edit-timeline sync")

    if args.dry_run:
        cmd = [find_binary("ffmpeg"), *build_command(info, plan, output)]
        print("      $ " + " ".join(_quote(c) for c in cmd))
        return True

    if output.exists() and not options.overwrite:
        print(f"      skipping: {output.name} exists (use --overwrite)")
        return False

    def _progress(frac: float) -> None:
        sys.stdout.write(f"\r      encoding... {frac * 100:5.1f}%")
        sys.stdout.flush()

    try:
        convert(info, plan, output, on_progress=_progress)
    except ToneMapUnsupported as exc:
        print(f"\n  ! {src.name}: {exc}", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"\n  ! {src.name}: conversion failed ({exc})", file=sys.stderr)
        return False

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"\r      done -> {output.name} ({size_mb:.1f} MB)          ")
    return True


def _process_heic(src: Path, args, is_batch: bool) -> bool:
    """Convert one HEIC/HEIF file to JPG. Return True on success (or dry-run)."""
    output = _resolve_output(src, args, ".jpg", is_batch)

    if output.resolve() == src.resolve():
        print(f"  ! {src.name}: output would overwrite the source; skipping", file=sys.stderr)
        return False

    print(f"  {src.name}  [HEIC]  ->  convert to JPG (quality {args.jpg_quality})")

    if args.dry_run:
        print(
            f'      $ sips -s format jpeg -s formatOptions {args.jpg_quality} '
            f'"{src}" --out "{output}"'
        )
        return True

    if output.exists() and not args.overwrite:
        print(f"      skipping: {output.name} exists (use --overwrite)")
        return False

    try:
        convert_heic_to_jpg(src, output, quality=args.jpg_quality)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {src.name}: conversion failed ({exc})", file=sys.stderr)
        return False

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"      done -> {output.name} ({size_mb:.1f} MB)")
    return True


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s or "," in s else s


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        inputs = _gather_inputs(args.input)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not inputs:
        print(f"No .mov/.heic files found in {args.input}", file=sys.stderr)
        return 1

    if any(f.suffix.lower() in _VIDEO_EXTS for f in inputs):
        try:
            ensure_ffmpeg()
        except FFmpegNotFound as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if any(f.suffix.lower() in _IMAGE_EXTS for f in inputs):
        try:
            ensure_sips()
        except SipsNotFound as exc:
            print(str(exc), file=sys.stderr)
            return 2

    options = _options_from_args(args)
    is_batch = args.input.is_dir()

    print(f"Converting {len(inputs)} file(s):")
    ok = 0
    for src in inputs:
        suffix = src.suffix.lower()
        if suffix in _VIDEO_EXTS:
            success = _process(src, args, options, is_batch)
        elif suffix in _IMAGE_EXTS:
            success = _process_heic(src, args, is_batch)
        else:
            print(f"  ! {src.name}: unsupported file type", file=sys.stderr)
            success = False
        if success:
            ok += 1

    print(f"\nDone: {ok}/{len(inputs)} succeeded.")
    return 0 if ok == len(inputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
