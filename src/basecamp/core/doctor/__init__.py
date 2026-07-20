"""``basecamp doctor`` — config & runtime health check with opt-in repair.

Diagnoses the unified ``config.json`` (integrity, references, unused keys), the
environment prerequisites, and reclaimable runtime state; repairs only when a
flag asks for it. The command surface is :func:`run_doctor`; the check, repair,
and clean logic lives in the submodules.
"""

from __future__ import annotations

from basecamp.core.doctor.run import run_doctor

__all__ = ["run_doctor"]
