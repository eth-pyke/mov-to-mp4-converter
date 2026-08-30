# mov-to-mp4-converter

Convert iPhone `.mov` files to edit-ready `.mp4` while preserving quality — built
so the footage looks **correct**, not washed-out, when imported into DaVinci
Resolve and other editors. Also converts `.heic`/`.heif` photos to `.jpg`.

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
- **ffmpeg + ffprobe** on your PATH, for `.mov` conversion. For full HDR
  tone-mapping, install a build that includes the `zscale` (zimg) filter:

  ```sh
  brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg
  ```

  A plain `brew install ffmpeg` also works but ships without `zscale`; the tool
  then falls back to a lower-quality HDR conversion (and tells you so).
- **macOS's `sips`** (built in, nothing to install), for `.heic`/`.heif` ->
  `.jpg` conversion. HEIC support is therefore macOS-only.

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

# HEIC -> JPG (single file, or a folder mixing .mov and .heic)
python convert.py photo.heic
python convert.py ./iphone-clips/ -o ./converted/
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
| `--jpg-quality N` | JPEG quality 0-100 for HEIC->JPG conversion (default `90`). |

## Web UI (local)

Prefer drag-and-drop? Launch the local browser app:

```sh
python serve.py
```

It opens `http://127.0.0.1:8000` in your browser. Drop `.mov` or `.heic` files
onto the page, pick an output folder, and hit **Convert**. Each file shows what
it detected (e.g. `hevc 10-bit HDR → tone-map HDR→SDR`, or `HEIC image →
convert to JPG`), a live progress bar, and where it saved — plus a
**Download** button.

It's a **local** app: files are uploaded to the localhost server (they never
leave your machine), converted with the same core and real ffmpeg as the CLI,
and written to your chosen folder. No third-party Python packages — just the
standard library. `python serve.py --port N` / `--no-open` adjust the port and
browser auto-open.

## How it decides

```
.mov source is H.264 8-bit SDR, no flags forcing a re-encode
        └── remux (stream copy, lossless, instant)
.mov otherwise
        └── re-encode to H.264 MP4
              ├── HDR source (default)  → tone-map HDR → SDR Rec.709
              ├── HDR source + --hdr     → preserve 10-bit HDR
              └── --cfr                  → normalize VFR → CFR
.heic / .heif source
        └── convert to JPG via sips (--jpg-quality controls quality)
```

## Project layout

```
convert.py            # CLI entry point: python convert.py ...
serve.py              # Web UI entry point: python serve.py
converter/            # reusable core (no UI knowledge)
  probe.py            # ffprobe -> MediaInfo (codec/HDR/VFR/rotation/audio)
  decisions.py        # MediaInfo + Options -> ConversionPlan (codec-agnostic)
  convert.py          # ConversionPlan -> ffmpeg command (+ progress)
  ffmpeg.py           # locate binaries, run subprocess, parse progress
  heic.py             # HEIC/HEIF -> JPG via macOS `sips`
  cli.py              # argparse + batching, dispatches .mov vs .heic
webui/                # local browser app
  server.py           # stdlib HTTP server; imports the converter core
  static/             # index.html, styles.css, app.js
```

Both front-ends (CLI and web) drive the same `probe` → `decisions` → `convert`
core for video — it has no UI knowledge. `--prores` flows through the same
`OutputFormat` abstraction. HEIC->JPG is a separate, simpler path (`heic.py`)
since it needs no codec/HDR decision-making.
