#!/usr/bin/env python3
"""Launch the local browser UI: `python serve.py [--port N] [--no-open]`.

Thin shim over webui.server so the app runs without installation.
"""

import argparse

from webui.server import run


def main() -> int:
    p = argparse.ArgumentParser(description="Local browser UI for the MOV->MP4 converter.")
    p.add_argument("--port", type=int, default=8000, help="Port to serve on (default 8000).")
    p.add_argument("--no-open", action="store_true", help="Don't auto-open the browser.")
    args = p.parse_args()
    return run(port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
