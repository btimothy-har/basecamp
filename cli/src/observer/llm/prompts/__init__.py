"""Prompt templates for the observer extraction pipeline.

Prompts are stored as .txt files and pre-loaded into a cache at import time.
Usage::

    from observer.llm import prompts
    prompts.extract            # → contents of extract.txt
    prompts.tool_summarize     # → contents of tool_summarize.txt
"""

from importlib import resources

from observer.exceptions import PromptAttributeError

_cache: dict[str, str] = {}
_package = resources.files(__name__)
for _file in _package.iterdir():
    if hasattr(_file, "name") and _file.name.endswith(".txt"):
        _cache[_file.name.removesuffix(".txt")] = _file.read_text(encoding="utf-8")


def __getattr__(name: str) -> str:
    try:
        return _cache[name]
    except KeyError:
        raise PromptAttributeError(__name__, name) from None
