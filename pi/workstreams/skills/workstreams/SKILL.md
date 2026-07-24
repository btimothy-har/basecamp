---
name: workstreams
description: "Shape and stage durable workstream records with the workstream tools. Keywords: workstream, create_workstream, launch_workstream, dossier, slug, pi --workstream, stage execution."
---

# Workstreams

Shaping the record and staging execution are separate steps. Do them in that order, and never treat staging as starting.

## Shape the record

`create_workstream` writes the durable workstream from a dossier-backed brief (label, brief, optional constraints) and returns its **id** (internal `ws_<uuid>`) and **slug** (a three-word readable id). It is record-only: no worktree, no pane, no agent.

Before creating, call `list_workstreams` (repo-neutral, filterable by dossier path, slug/label, or status) to find existing workstreams for the dossier. If a matching one exists, edit it or point the user to it instead of creating a duplicate.

When priorities or scope change, `edit_workstream` revises the record's content in place — it bumps the version and **keeps the old version**, so refining a brief never discards the prior one. Identity, dossier pointer, worktree, and attached agents are unchanged, and the change takes effect the next time an agent runs `pi --workstream`; a session already running keeps its brief until you reach out or it restarts.

Use `set_workstream_status` to close a workstream when its work is done.

## Stage execution

When the user chooses a workstream, `launch_workstream` (by its id or slug) provisions its `copilot/<slug>` worktree and best-effort opens a Herdr pane on it. The worktree keeps the generic `copilot/<slug>` name; its initial branch is work-derived (`bt/…`, or your default prefix), and `worktreeSlug` sets that branch name.

`launch_workstream` requires an existing workstream — create it first. **It does not start an agent.** Tell the user to run `pi --workstream` in the opened pane (the bare form infers the slug from the worktree label), or `cd <worktree-path> && pi --workstream=<slug>` if no pane opened or Herdr failed. That launch command loads the latest brief into the session and attaches the session as a workstream agent in the daemon.

Because launch is decoupled from the record, the same workstream can be launched into a different repo for cross-repo coordination without creating a duplicate.

## Pull current state

To refresh a workstream's state, pull it on demand. Find it with `list_workstreams` — a single-identifier lookup returns the workstream plus its joined agent rows — and read the attached agent handles. A handle is only present once the user has launched `pi --workstream` in the pane; when it is, use it with `ask_agent` (or `message_agent`) to request a concise current-state summary.

Treat that handle as a contact address only, not as list/wait/retask authority.
