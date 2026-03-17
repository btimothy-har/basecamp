"""Logseq prompt loading — shared by reflect, plan, and future Logseq commands."""

from importlib import resources

from core.constants import USER_PROMPTS_DIR


def load_system_prompt() -> str:
    """Load the Logseq system prompt, checking user dir before package default.

    User override: ``~/.basecamp/prompts/logseq.md``
    Package default: ``core.prompts.logseq/system.md``
    """
    user_path = USER_PROMPTS_DIR / "logseq.md"
    if user_path.exists():
        return user_path.read_text()
    return resources.files("core.prompts.logseq").joinpath("system.md").read_text()


def load_user_prompt(name: str) -> str:
    """Load a Logseq command's user prompt by name.

    User override: ``~/.basecamp/prompts/{name}.md``
    Package default: ``core.prompts.logseq/{name}.md``
    """
    user_path = USER_PROMPTS_DIR / f"{name}.md"
    if user_path.exists():
        return user_path.read_text()
    return resources.files("core.prompts.logseq").joinpath(f"{name}.md").read_text()
