"""Context file discovery."""

from core.constants import USER_CONTEXT_DIR


def available() -> list[str]:
    """Return sorted names of available context files from the user context directory."""
    if not USER_CONTEXT_DIR.exists():
        return []
    return sorted(p.stem for p in USER_CONTEXT_DIR.glob("*.md"))
