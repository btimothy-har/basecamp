"""The Claude Code session-lifecycle hub — a self-contained, promotable section.

This package is everything the Claude Code integration needs from the hub and
nothing it does not: runtime paths, a minimal sessions store, the HTTP-over-UDS
daemon (health + register/end/list), and the ensure-daemon client the hooks call.
It depends only on the shared frame contract (:mod:`basecamp.hub.frames`) and the
core shell — never on the legacy Pi swarm service graph.

It is deliberately parallel to the Pi runtime rather than woven into it: at
promotion the runtime root flips off ``.pi`` (see :mod:`basecamp.hub.claude.paths`)
and the Pi side is deleted, with no import untangling required here.
"""

from __future__ import annotations
