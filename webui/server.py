"""Stdlib HTTP server backing the local browser UI.

Endpoints:
  GET  /                      -> the app page
  GET  /static/<file>         -> static assets (css/js)
  POST /api/convert?name=&outdir=&hdr=  (raw file bytes as body)
                              -> writes a temp copy, probes it, starts a
                                 background conversion, returns a job id
                                 (.mov -> .mp4 via ffmpeg, .heic/.heif -> .jpg
                                 via sips)
  GET  /api/status?job=<id>   -> job progress/status as JSON
  GET  /api/download?job=<id> -> the converted file

Binds to 127.0.0.1 only: it is a single-user local tool, so uploaded bytes and
chosen output paths never leave the machine.
"""

from __future__ import annotations

import json
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

from converter.convert import convert
from converter.decisions import Options, plan_conversion
from converter.ffmpeg import ensure_available
from converter.heic import EXTENSIONS as HEIC_EXTENSIONS
from converter.heic import convert_heic_to_jpg
from converter.probe import probe

STATIC_DIR = Path(__file__).parent / "static"
_UPLOAD_CHUNK = 1 << 20  # 1 MiB
_IMAGE_EXTS = set(HEIC_EXTENSIONS)
_DOWNLOAD_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".jpg": "image/jpeg",
}


@dataclass
class Job:
    id: str
    name: str
    source_desc: str = ""
    action: str = ""
    status: str = "queued"          # queued | converting | done | error
    progress: float = 0.0           # 0.0 - 1.0
    output_path: Optional[str] = None
    error: Optional[str] = None


class Jobs:
    """Thread-safe registry of conversion jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, name: str) -> Job:
        job = Job(id=uuid.uuid4().hex, name=name)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)


JOBS = Jobs()
# Keep temp dirs alive for the process lifetime so downloads keep working.
_TEMPDIRS: list = []


def _unique_path(path: Path) -> Path:
    """Return ``path`` or, if it exists, ``name (2).ext`` etc. so we never clobber."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    n = 2
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _run_video_conversion(job: Job, src: Path, outdir: Path, options: Options) -> None:
    try:
        info = probe(src)
        plan = plan_conversion(info, options)
        outdir.mkdir(parents=True, exist_ok=True)
        out = _unique_path(outdir / (Path(job.name).stem + plan.output_format.extension))
        job.status = "converting"
        convert(info, plan, out, on_progress=lambda f: setattr(job, "progress", f))
        job.output_path = str(out)
        job.progress = 1.0
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        job.error = str(exc)
        job.status = "error"


def _run_heic_conversion(job: Job, src: Path, outdir: Path) -> None:
    try:
        outdir.mkdir(parents=True, exist_ok=True)
        out = _unique_path(outdir / (Path(job.name).stem + ".jpg"))
        job.status = "converting"
        convert_heic_to_jpg(src, out)
        job.output_path = str(out)
        job.progress = 1.0
        job.status = "done"
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        job.error = str(exc)
        job.status = "error"


class Handler(BaseHTTPRequestHandler):
    server_version = "MovConverterUI"

    # Quieter logging: one line per request is enough.
    def log_message(self, fmt, *args):  # noqa: D401
        pass

    # ---- helpers -------------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str, download_name=None):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{download_name}"'
            )
        self.end_headers()
        self.wfile.write(data)

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/":
            return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")

        if route.startswith("/static/"):
            name = route[len("/static/"):]
            asset = (STATIC_DIR / name).resolve()
            if STATIC_DIR.resolve() in asset.parents and asset.is_file():
                ctype = {
                    ".css": "text/css",
                    ".js": "text/javascript",
                    ".html": "text/html; charset=utf-8",
                }.get(asset.suffix, "application/octet-stream")
                return self._send_file(asset, ctype)
            return self._send_json({"error": "not found"}, 404)

        if route == "/api/status":
            qs = parse_qs(parsed.query)
            job = JOBS.get(qs.get("job", [""])[0])
            if not job:
                return self._send_json({"error": "unknown job"}, 404)
            return self._send_json(asdict(job))

        if route == "/api/download":
            qs = parse_qs(parsed.query)
            job = JOBS.get(qs.get("job", [""])[0])
            if not job or not job.output_path:
                return self._send_json({"error": "not ready"}, 404)
            out = Path(job.output_path)
            ctype = _DOWNLOAD_CONTENT_TYPES.get(out.suffix.lower(), "application/octet-stream")
            return self._send_file(out, ctype, download_name=out.name)

        return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/convert":
            return self._send_json({"error": "not found"}, 404)

        qs = parse_qs(parsed.query)
        name = qs.get("name", ["clip.mov"])[0]
        outdir = Path(qs.get("outdir", ["~/Downloads"])[0]).expanduser()
        preserve_hdr = qs.get("hdr", ["0"])[0] == "1"

        # Stream the uploaded bytes to a temp file (avoids loading it all in RAM).
        length = int(self.headers.get("Content-Length", 0))
        tmp = TemporaryDirectory()
        _TEMPDIRS.append(tmp)
        src = Path(tmp.name) / name
        remaining = length
        with open(src, "wb") as fh:
            while remaining > 0:
                chunk = self.rfile.read(min(_UPLOAD_CHUNK, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                remaining -= len(chunk)

        job = JOBS.create(name)

        if Path(name).suffix.lower() in _IMAGE_EXTS:
            job.source_desc = "HEIC image"
            job.action = "convert to JPG"
            threading.Thread(
                target=_run_heic_conversion, args=(job, src, outdir), daemon=True
            ).start()
            return self._send_json(asdict(job), 200)

        # Probe now so the UI can immediately show what will happen.
        try:
            info = probe(src)
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.error = f"could not read file: {exc}"
            return self._send_json(asdict(job), 200)

        options = Options(preserve_hdr=preserve_hdr)
        plan = plan_conversion(info, options)
        job.source_desc = (
            f"{info.video_codec} {info.bit_depth}-bit"
            f"{' HDR' if info.is_hdr else ''}{' VFR' if info.is_vfr else ''}"
        )
        job.action = plan.summary

        threading.Thread(
            target=_run_video_conversion, args=(job, src, outdir, options), daemon=True
        ).start()

        return self._send_json(asdict(job), 200)


def run(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True) -> int:
    try:
        ensure_available()
    except Exception as exc:  # noqa: BLE001
        print(exc)
        return 2

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Converter UI running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()
    return 0
