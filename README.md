# mov-to-mp4-converter

Convert iPhone `.mov` files to edit-ready `.mp4` while preserving quality — built
so the footage looks **correct**, not washed-out, when imported into DaVinci
Resolve and other editors.

## Why this exists

Modern iPhones record **HEVC 10-bit HDR (Dolby Vision)** by default. Dropped onto
a standard Rec.709 timeline, that footage is misinterpreted and looks
washed-out / desaturated — the #1 "iPhone video looks bad in my editor" problem.
It's a *color* problem, not a codec-quality problem. This tool:

- **Auto-detects** each clip (codec, bit depth, HDR, VFR) with `ffprobe`.
- **Tone-maps HDR → SDR (Rec.709)** by default so colors look right anywhere.
- **Remuxes losslessly** when a clip is already H.264 SDR (instant, zero quality loss).
- **Re-encodes at high quality** (`x264 -crf 18 -preset slow`) otherwise.
- Keeps the original **AAC audio** untouched and adds `+faststart`.

## Requirements

- **Python 3** (standard library only — no `pip install` needed).
- **ffmpeg + ffprobe** on your PATH. For full HDR tone-mapping, install a build
  that includes the `zscale` (zimg) filter:

  ```sh
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg
  ```

  A plain `brew install ffmpeg` also works but ships without `zscale`; the tool
  then falls back to a lower-quality HDR conversion (and tells you so).

## Usage

```sh
# Single file (writes alongside as .mp4)
python convert.py clip.mov

# Choose an output path
python convert.py clip.mov -o ~/Desktop/clip.mp4

# Whole folder (all .mov) into an output directory
python convert.py ./iphone-clips/ -o ./converted/

# See the plan + exact ffmpeg command without running anything
python convert.py clip.mov --dry-run
```

### Options

| Flag | Effect |
|------|--------|
| `-o, --output` | Output file (single input) or output directory (folder input). |
| `--hdr` | Preserve 10-bit HDR instead of tone-mapping to SDR. |
| `--cfr` | Normalize variable frame rate to constant (cleaner edit sync). |
| `--crf N` | x264 quality, lower = better (default `18`). |
| `--preset P` | x264 preset (default `slow`). |
| `--force-reencode` | Always re-encode, even when a lossless remux is possible. |
| `--prores` | *(experimental)* Output ProRes 422 HQ `.mov` — the edit-ideal format. |
| `--overwrite` | Overwrite existing outputs. |
| `--dry-run` | Print the plan and ffmpeg command only. |

## How it decides

```
source is H.264 8-bit SDR, no flags forcing a re-encode
        └── remux (stream copy, lossless, instant)
otherwise
        └── re-encode to H.264 MP4
              ├── HDR source (default)  → tone-map HDR → SDR Rec.709
              ├── HDR source + --hdr     → preserve 10-bit HDR
              └── --cfr                  → normalize VFR → CFR
```

## Project layout

```
convert.py            # entry point: python convert.py ...
converter/
  probe.py            # ffprobe -> MediaInfo (codec/HDR/VFR/rotation/audio)
  decisions.py        # MediaInfo + Options -> ConversionPlan (codec-agnostic)
  convert.py          # ConversionPlan -> ffmpeg command (+ progress)
  ffmpeg.py           # locate binaries, run subprocess, parse progress
  cli.py              # argparse + batching (the only user-facing module)
```

The `probe` → `decisions` → `convert` core has no CLI knowledge, so a future
GUI can import and drive it directly. `--prores` already flows through the same
`OutputFormat` abstraction.
