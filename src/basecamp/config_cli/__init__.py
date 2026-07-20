"""The ``basecamp config`` CLI shell — project/env/alias porcelain + generic plumbing.

A composition layer above both ``core`` (settings, model aliases, projects) and
``workspace`` (environments), so it lives beside ``cli.py`` rather than inside
``core`` — keeping ``core`` a true leaf that imports no other domain.
"""
