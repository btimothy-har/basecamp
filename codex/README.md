# Basecamp Codex Package

This directory contains the Codex-native package for Basecamp engineering
workflows.

It is a first-class Codex package, not a compatibility layer for Pi and not a
runtime. Codex owns its app UI, worktrees, approvals, Plan mode, and subagents.
Files here provide Codex-native operating guidance, skills, custom agents, and
packaging metadata that can be installed into Codex locations by
`basecamp sync codex`.

Model-facing instructions in this directory should not refer to Basecamp, Pi, or
Pi-only runtime behavior. They should read as native Codex guidance.

## Contents

- `projection.toml` declares the package manifest used by the current installer.
- `instructions/` contains durable Codex operating guidance installed into
  `developer_instructions`.
- `agents/` contains Codex custom agent definitions.
- `docs/` contains package design notes. These files are not installed into
  Codex; they explain how this package should use Codex-native surfaces.
- Skill entries in `projection.toml` point to canonical source directories and
  are materialized into the user skill location, usually as symlinks.

`basecamp sync codex` is the installer. This directory is the source of truth.
