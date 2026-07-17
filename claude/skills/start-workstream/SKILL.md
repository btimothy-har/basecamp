---
name: start-workstream
description: "Pick up a staged workstream and execute it: read its brief and dossier, then implement it directly. Triggers: 'start workstream', 'start-workstream', 'pick up the workstream', 'start the workstream in this worktree', 'start workstream <slug>', 'begin work on this workstream'. Run in a worktree copilot provisioned, or name a workstream by its slug from any repo."
---

# Start Workstream

You are picking up a **staged workstream** — a piece of work copilot shaped and provisioned. Your job is to *execute* it: implement the brief directly, and keep the workstream's shared-Logseq record current as you go. (This is the opposite posture from copilot, which stages and hands off but never implements.)

## 1. Find out which workstream this is

Resolve the workstream and where its brief lives. Two entry modes:

- **You are in the pane copilot opened** (the usual case) — infer it from the current worktree:

  ```bash
  basecamp workstream current
  ```

- **You want to start a named workstream from anywhere** (a different repo, or any directory) — resolve it by slug:

  ```bash
  basecamp workstream show <slug>
  ```

Either prints the workstream's `label`, `slug`, `status`, `repo`, `worktree`, and — the important one — a `dossier:` path pointing at its shared-Logseq work page. It reports pointers, not content: the brief itself is in the dossier file.

If the command errors (not in a git worktree, no workstream registered, or an unknown slug), stop and tell the user — this worktree was not staged by copilot, the slug is wrong, or the daemon is not running. Do not guess a workstream.

## 2. Read the brief from the dossier

Read the `dossier:` path from step 1 with the Read tool. That page (`work__<org>__<repo>__<slug>`) is the durable brief copilot seeded: objective, scope, boundaries, dependencies, validation expectations, and the done signal. It is the source of truth for what this workstream is.

If it helps orient, you may also read the repo cockpit (`basecamp://logseq/cockpit`) for how this workstream fits the broader repo picture — but the dossier is your primary brief.

## 3. Decide where to execute

Compare the workstream's `repo` (from step 1) to the repository you are in now:

- **Same repo (its home)** — the workstream's default worktree is `copilot/<slug>` under this repo. Work there: if you are not already in it, `cd` to it (or open it) and execute on its branch.
- **A different repo** — the brief is portable. Execute it **right here**, in the current repo, creating a worktree or branch as fits the work. The dossier stays the workstream's shared record no matter where you execute (step 5).

A workstream is a brief plus a dossier; agents attach to the *workstream*, so it can have many workers across repos. The provisioned worktree is copilot's default home for it, not a hard binding.

## 4. Attach this session to the workstream

Register yourself as a worker on the workstream, from the worktree you will execute in:

```bash
basecamp workstream attach <slug>
```

This links your session (agent) to the workstream, carrying this repo and worktree. Many agents can attach — that is what makes a workstream multi-worker and portable; the daemon derives who is live from attached sessions. Attach from the worktree you are actually working in, so the recorded worktree is correct.

## 5. Execute the brief

Implement the work directly, on a branch. You own execution:

- Work in the workstream's worktree (home repo) or the worktree/branch you chose here (portable). You may spin up ephemeral child worktrees (native `.claude/worktrees/`) for isolated sub-work.
- Decompose, prioritize, and size the work from the brief. The brief is intentionally stretchable — turn it into concrete steps.
- Validate as the brief expects (tests, checks, review) before treating a slice as done.
- Do not push, open a PR, or merge unless the user asks.

## 6. Keep the dossier and journal current

You are the workstream's own reporter — copilot reads what you write here to keep the repo picture current, so keep it durable and legible.

- **Dossier** (`work__<org>__<repo>__<slug>`): keep the durable state current — decisions made, blockers hit, scope changes, and the done signal when you reach it. This is the workstream's living record, wherever you executed.
- **Journal**: log dated activity as blocks that tag the day in the graph's configured display format, so Logseq's Linked References assemble one unified daily view — e.g. `- DONE wired the token refresh path [[Jul 17th, 2026]]` (Logseq stores that day as `journals/2026_07_17.md`). If unsure of the graph's date format, confirm it once from an existing journal file. Tag the dossier too (`[[work__<org>__<repo>__<slug>]]`) so the timeline stitches onto its page.

Write only your own workstream's pages — the dossier and your dated journal blocks. Do not write the repo cockpit; that is copilot's. Capture durable coordination value (decisions, blockers, done), not raw activity noise.

