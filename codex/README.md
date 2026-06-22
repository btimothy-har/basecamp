# Basecamp Codex Projection

This directory contains the Codex-native projection of Basecamp behavior.

It is an adapter package, not a runtime. Codex owns its app UI, worktrees,
approvals, Plan mode, and subagents. Files here provide portable operating
guidance, skills, custom agents, and packaging metadata that can be installed
into Codex-native locations by `basecamp sync codex`.

Model-facing instructions in this directory should not refer to Basecamp, Pi, or
Pi-only runtime behavior. They should read as native Codex guidance.

## Contents

- `projection.toml` declares the projection manifest.
- `instructions/` contains durable Codex operating guidance installed into
  `developer_instructions`.
- `agents/` contains Codex custom agent definitions.
- Skill entries in `projection.toml` point to canonical source directories and
  are materialized into the user skill location, usually as symlinks.

`basecamp sync codex` is the installer. This directory is the source of truth.
