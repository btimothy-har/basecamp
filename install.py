#!/usr/bin/env python3
# /// script
# dependencies = [
#   "rich>=13.0",
# ]
# requires-python = ">=3.12"
# ///
"""Bootstrap installer for basecamp.

Run this once after cloning (``uv run install.py`` / ``make install``) to install
the `basecamp` tool onto PATH and wire it into Claude Code. Subsequent
re-runs of the wiring only: `basecamp install`.
"""

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
# basecamp is one ordinary package under src/; add it to sys.path so this
# bootstrap can import basecamp.install before the tool is installed.
sys.path.insert(0, str(REPO_DIR / "src"))

from basecamp.install import run_bootstrap  # noqa: E402


def main() -> None:
    run_bootstrap()


if __name__ == "__main__":
    main()
