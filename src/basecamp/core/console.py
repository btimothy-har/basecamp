"""Shared rich consoles for basecamp's CLI output.

One ``console`` (stdout) and one ``err_console`` (stderr), imported wherever
basecamp prints — the CLI shell, ``setup``, ``doctor``, the installer, and the
workspace display helpers. Centralized in ``core`` (the base every package
imports) so nothing re-instantiates its own pair or reaches into a sibling
domain for one.
"""

from __future__ import annotations

from rich.console import Console

#: Standard-output console for user-facing CLI output.
console = Console()

#: Standard-error console for errors and diagnostics.
err_console = Console(stderr=True)
