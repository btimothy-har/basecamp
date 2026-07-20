"""Unified data models for the basecamp config document.

Every record that lives in the unified ``~/.pi/basecamp/config.json`` is modeled
here as a pure pydantic type — no IO, no settings access, no other-domain
imports — so the storage layer (:mod:`basecamp.core.settings`), the per-section
loaders, and the CLI all validate against one shared definition rather than
re-declaring the shape.

Kept deliberately domain-neutral: only models for the shared config document
belong here. Domain-internal shapes (hub wire frames, companion snapshots,
persistence rows) stay in their own domains, which the ``core imports no other
domain`` rule requires anyway.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectConfig(BaseModel):
    """A single entry of the ``projects`` section."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    additional_dirs: list[str] = Field(default_factory=list)
    description: str = ""
    working_style: str | None = None
    context: str | None = None


class EnvironmentConfig(BaseModel):
    """A single entry of the ``environments`` section (per-repo setup command)."""

    model_config = ConfigDict(extra="forbid")

    setup: str | None = None


class LogseqConfig(BaseModel):
    """The ``logseq`` section: an optional Logseq graph directory."""

    model_config = ConfigDict(extra="forbid")

    graph_dir: str | None = None
