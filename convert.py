#!/usr/bin/env python3
"""Top-level entry point: `python convert.py INPUT [options]`.

Thin shim over converter.cli so the tool runs without installation.
"""

from converter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
