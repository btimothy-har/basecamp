"""Syntax highlighting helpers for the companion TUI."""

from __future__ import annotations

from pygments.lexer import Lexer
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound


def lexer_for_filename(file_path: str) -> Lexer:
    """Return the best lexer for a filename, falling back to plain text."""

    try:
        return get_lexer_for_filename(file_path)
    except ClassNotFound:
        return TextLexer()
