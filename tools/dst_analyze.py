#!/usr/bin/env python3
"""CLI wrapper - the implementation lives in engine/stitchcraft_engine/dst_analyze.py (so the server can use it too)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from stitchcraft_engine.dst_analyze import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1:])
