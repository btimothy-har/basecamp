"""Utilities for basecamp.

Re-exports shared primitives from :mod:`basecamp_core` so existing
``basecamp_cli`` imports keep working during the package split.
"""

from __future__ import annotations

from basecamp_core.files import atomic_write_json

__all__ = ["atomic_write_json"]
