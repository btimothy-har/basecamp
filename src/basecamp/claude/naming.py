"""Three-word readable slug generation for workstreams.

A workstream's slug is a globally-unique, readable id like ``brave-otter-fox``
(adjective-adjective-noun). The MCP tool mints it and the daemon enforces
uniqueness via the ``slug UNIQUE`` constraint, so ``generate`` retries against an
``is_taken`` probe (the daemon 409) rather than needing a huge bank — a modest
word list keeps the collision rate low enough that a few retries always suffice.

Randomness note: the daemon/store code forbids ``random`` in some contexts, but
this is a plain CLI/MCP-tool path (not the resumable workflow runtime), so
``secrets.choice`` is fine and needs no seeding.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

_ADJECTIVES = (
    "amber",
    "brave",
    "bright",
    "calm",
    "clever",
    "crisp",
    "eager",
    "fair",
    "gentle",
    "glad",
    "keen",
    "kind",
    "lively",
    "lucky",
    "mellow",
    "merry",
    "nimble",
    "noble",
    "proud",
    "quick",
    "quiet",
    "rapid",
    "ready",
    "sharp",
    "silent",
    "smooth",
    "solid",
    "spry",
    "steady",
    "stout",
    "swift",
    "vivid",
    "warm",
    "wise",
    "witty",
    "zesty",
)

_NOUNS = (
    "otter",
    "fox",
    "hawk",
    "wren",
    "lark",
    "finch",
    "heron",
    "raven",
    "sparrow",
    "falcon",
    "badger",
    "beaver",
    "marten",
    "lynx",
    "ibex",
    "elk",
    "moose",
    "bison",
    "heron",
    "crane",
    "egret",
    "pika",
    "vole",
    "shrew",
    "willow",
    "cedar",
    "birch",
    "alder",
    "maple",
    "aspen",
    "spruce",
    "juniper",
    "harbor",
    "meadow",
    "ridge",
    "delta",
)

_MAX_ATTEMPTS = 50


def generate_slug(is_taken: Callable[[str], bool] | None = None) -> str:
    """Return a fresh ``adjective-adjective-noun`` slug not rejected by ``is_taken``.

    ``is_taken(slug)`` returns True when the candidate collides (e.g. the daemon
    already has it); when omitted, the first candidate is returned. Raises
    :class:`RuntimeError` only if every one of :data:`_MAX_ATTEMPTS` candidates
    collides — vanishingly unlikely given the bank size, and a signal the caller
    should surface rather than loop forever.
    """

    for _ in range(_MAX_ATTEMPTS):
        candidate = "-".join(
            (
                secrets.choice(_ADJECTIVES),
                secrets.choice(_ADJECTIVES),
                secrets.choice(_NOUNS),
            )
        )
        if is_taken is None or not is_taken(candidate):
            return candidate
    msg = "could not generate a unique workstream slug"
    raise RuntimeError(msg)
