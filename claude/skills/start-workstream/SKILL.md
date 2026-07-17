---
name: start-workstream
description: "Pick up the workstream staged in the current worktree: read its brief and dossier, then execute it directly. Triggers: 'start workstream', 'start-workstream', 'pick up the workstream', 'start the workstream in this worktree', 'begin work on this workstream'. Run this in a worktree copilot provisioned with create_workstream."
---

# Start Workstream

You are picking up a **staged workstream** — a piece of work copilot shaped and provisioned into this worktree. Your job is to *execute* it: implement the brief directly, and keep the workstream's shared-Logseq record current as you go. (This is the opposite posture from copilot, which stages and hands off but never implements.)

## 1. Find out which workstream this is

The worktree you are in belongs to a workstream. Ask the daemon which one, and where its brief lives:

```bash
basecamp workstream current
```

This prints the workstream's `label`, `slug`, and — the important line — a `dossier:` path pointing at its shared-Logseq work page. It reports pointers, not content: the brief itself is in the dossier file, not in this output.

If the command errors (not in a git worktree, or no workstream is registered for it), stop and tell the user — this worktree was not staged by copilot, or the daemon is not running. Do not guess a workstream.

## 2. Read the brief from the dossier

Read the `dossier:` path from step 1 with the Read tool. That page (`work__<org>__<repo>__<slug>`) is the durable brief copilot seeded: objective, scope, boundaries, dependencies, validation expectations, and the done signal. It is the source of truth for what this workstream is.

If it helps orient, you may also read the repo cockpit (`basecamp://logseq/cockpit`) for how this workstream fits the broader repo picture — but the dossier is your primary brief.

## 3. Execute the brief

Implement the work directly in this worktree, on its branch. You own execution:

- Work only in this worktree. It is a permanent worktree for this workstream; you may spin up ephemeral child worktrees (native `.claude/worktrees/`) for isolated sub-work, but this is the workstream's home.
- Decompose, prioritize, and size the work from the brief. The brief is intentionally stretchable — turn it into concrete steps.
- Validate as the brief expects (tests, checks, review) before treating a slice as done.
- Do not push, open a PR, or merge unless the user asks.

## 4. Keep the dossier and journal current

You are the workstream's own reporter — copilot reads what you write here to keep the repo picture current, so keep it durable and legible.

- **Dossier** (`work__<org>__<repo>__<slug>`): keep the durable state current — decisions made, blockers hit, scope changes, and the done signal when you reach it. This is the workstream's living record.
- **Journal**: log dated activity as blocks that tag the day in the graph's configured display format, so Logseq's Linked References assemble one unified daily view — e.g. `- DONE wired the token refresh path [[Jul 17th, 2026]]` (Logseq stores that day as `journals/2026_07_17.md`). If unsure of the graph's date format, confirm it once from an existing journal file. Tag the dossier too (`[[work__<org>__<repo>__<slug>]]`) so the timeline stitches onto its page.

Write only your own workstream's pages — the dossier and your dated journal blocks. Do not write the repo cockpit; that is copilot's. Capture durable coordination value (decisions, blockers, done), not raw activity noise.
