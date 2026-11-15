"""Convenience wrapper: show one video's full production state.

Usage:
    python scripts/produce_story.py --video TMA-0001
    python scripts/produce_story.py --video TMA-0001 --json

This prints the status history, stored artifacts, QC result and the next action.
Rendering and narration are Phase 2/3 and are not implemented yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midnight_archive.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["show", *sys.argv[1:]]))
