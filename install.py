#!/usr/bin/env python3
"""Bootstrap installer for basecamp.

Run this once after cloning (``uv run install.py`` / ``make install``) to install
the `basecamp` tool onto PATH and wire it into Claude Code. Subsequent
re-runs of the wiring only: `basecamp install`.

Deliberately carries no PEP 723 ``# /// script`` block: this bootstrap imports
``basecamp.install`` and runs ``execute_install`` in-process, which pulls in the
project's full dependency closure (pydantic, rich, …). Under ``uv run`` an inline
metadata block would isolate the script to only its declared deps; without one,
``uv run install.py`` runs inside the project environment, so the dependency set
is single-sourced from ``pyproject.toml`` / ``uv.lock`` rather than hand-mirrored
here. The project's own ``requires-python >=3.12`` still applies.
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
