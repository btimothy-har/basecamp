"""Prompt templates for the observer extraction pipeline.

Prompts are stored as .txt files and loaded lazily via module ``__getattr__``
(PEP 562).  Usage::

    from observer import prompts
    prompts.extract        # → contents of extract.txt
    prompts.summarize      # → contents of summarize.txt
"""

from importlib import resources

from observer.exceptions import PromptAttributeError


def __getattr__(name: str) -> str:
    path = resources.files(__name__).joinpath(f"{name}.txt")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    raise PromptAttributeError(__name__, name)
