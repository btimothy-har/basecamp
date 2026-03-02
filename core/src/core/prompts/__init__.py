"""Prompt resources for basecamp.

Submodules:
    system          — System prompt loading and assembly
    working_styles  — Working style discovery and loading
    project_context — Context file discovery
"""

from core.prompts import project_context, system, working_styles

__all__ = [
    "project_context",
    "system",
    "working_styles",
]
