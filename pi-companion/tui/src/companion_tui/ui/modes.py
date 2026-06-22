"""Body mode helpers for the companion TUI."""

from __future__ import annotations

BODY_MODES = ("dashboard-body", "diff-body", "files-body", "swarm-body")


def next_body_mode(current: str) -> str:
    """Return the next body mode id, wrapping around at the end."""

    if current not in BODY_MODES:
        return BODY_MODES[0]

    index = BODY_MODES.index(current)
    return BODY_MODES[(index + 1) % len(BODY_MODES)]
