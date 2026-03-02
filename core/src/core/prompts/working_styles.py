"""Working style prompt loading and discovery."""

from importlib import resources

from core.constants import USER_WORKING_STYLES_DIR
from core.exceptions import PromptNotFoundError


def available() -> list[str]:
    """Return sorted names of available working styles (user overrides + package defaults)."""
    styles: set[str] = set()

    if USER_WORKING_STYLES_DIR.exists():
        styles.update(p.stem for p in USER_WORKING_STYLES_DIR.glob("*.md"))

    pkg = resources.files("core.prompts._working_styles")
    for item in pkg.iterdir():
        name = getattr(item, "name", "")
        if name.endswith(".md"):
            styles.add(name.removesuffix(".md"))

    return sorted(styles)


def load(name: str) -> tuple[str, str]:
    """Load a working style prompt, checking user dir before package defaults.

    Args:
        name: The working style name (e.g. "engineering").

    Returns:
        Tuple of (content, source) where source identifies the origin.

    Raises:
        PromptNotFoundError: If not found in user dir or package defaults.
    """
    user_path = USER_WORKING_STYLES_DIR / f"{name}.md"
    if user_path.exists():
        return user_path.read_text(encoding="utf-8"), f"working_styles/{name}.md"

    pkg_file = resources.files("core.prompts._working_styles").joinpath(f"{name}.md")
    try:
        return pkg_file.read_text(), f"core.prompts/working_styles/{name}.md"
    except FileNotFoundError:
        raise PromptNotFoundError(user_path) from None
