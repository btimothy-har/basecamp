"""Local Pi transcript discovery."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pi_memory.constants import DEFAULT_TRANSCRIPT_ROOTS


def discover_transcript_paths(roots: Iterable[Path | str] | None = None) -> list[Path]:
    """Return deterministic local transcript JSONL paths under roots."""
    discovered: dict[Path, Path] = {}
    for root in DEFAULT_TRANSCRIPT_ROOTS if roots is None else roots:
        path = Path(root).expanduser()
        for transcript_path in _transcript_paths(path):
            discovered.setdefault(transcript_path.resolve(strict=False), transcript_path)

    return sorted(discovered.values(), key=lambda path: str(path))


def _transcript_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".jsonl" else []
    if not path.is_dir():
        return []
    return [candidate for candidate in path.rglob("*.jsonl") if candidate.is_file()]
