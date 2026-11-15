"""Convenience wrapper: python scripts/generate_ideas.py --count 15 --seed 123.

All arguments are passed to ``python -m midnight_archive ideas``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from midnight_archive.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["ideas", *sys.argv[1:]]))
