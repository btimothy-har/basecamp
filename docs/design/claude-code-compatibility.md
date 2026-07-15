# Claude Code Compatibility — Decision & Rationale

**Status:** DECIDED (2026-07) · **Scope:** Why basecamp standardizes on Claude Code, and how it maps · **Supersedes:** the launcher / full-system-prompt-replacement design this doc previously specified (abandoned — see §3) · **Delivery design:** [`claude/README.md`](../../claude/README.md) (the plugin + MCP context server) · **Prior art:** a working pre-Pi Claude Code app in deleted history (§5) · **Related:** [async-agents](./async-agents.md)

basecamp standardizes on **Claude Code as its single runtime** for both work and personal use; the Pi extension is retired rather than maintained in parallel. This document records the decision and its rationale. The *delivery* — a Claude Code plugin bundling native components plus a stdio MCP context server — is specified in [`claude/README.md`](../../claude/README.md); this doc is the *why* above it.

---

## 1. Decision

- **One runtime, not two.** The forcing question was never "Pi vs. Claude Code" but "one runtime or two." A Pi extension for work plus a Claude Code port for personal use is a 2× solo maintenance burden with no offsetting benefit — and "work = Pi" is a *choice*, not a constraint (no other user depends on basecamp-on-Pi). One runtime dissolves the cross-runtime convergence problem outright: no hub bridge, no two extensions, no shared-protocol tax.
- **The runtime is Claude Code.** basecamp becomes a Claude Code plugin; the Pi extension and its Python daemon are retired.

## 2. Rationale

- **Leverage over rebuild.** Most of basecamp exists to give Pi what Claude Code ships natively — MCP, subagents + workflows, skills, code review, browser tools, task/plan tracking, model selection, native git worktrees. That scaffolding is *retired, not lost*: the capability is native. Pi hand-builds every future feature; Claude Code inherits Anthropic's platform investment — including net-new capabilities (scheduling, routines, cloud agents) — for free.
- **No real capability loss.** The candidate losses did not survive scrutiny. (1) Full prompt control — §3 abandons *full replacement*, but the MCP-`instructions` + resources channel carries basecamp's project context natively, which is the need it served. (2) TUI — Claude Code's own is preferred. (3) Mature agent intercommunication — basecamp's own is *young, not mature* (the wire protocol has churned steadily, v15 → v23 and counting; mutative agents re-enabled at HEAD), so it is low-loss to drop and a burden to keep; Anthropic's Agent Teams is the maintained successor. Cross-session coordination, if still wanted, survives as an *optional* daemon-backed Tier-2 MCP layer ([`claude/README.md`](../../claude/README.md)), not a mandatory port.
- **Sunk cost is not a reason.** The hub daemon, companion TUI, and ~half the extension are real work, but sunk — and much of it existed only to compensate for Pi's barebones runtime.
- **Situational awareness without the hub.** The one durable want the hub served splits cleanly: in-session observability → external tools (Herdr / hunk.dev); cross-session context continuity → the dossier (a shared Logseq/markdown record). Leverage-don't-build applies here too.

## 3. Delivery: plugin, not launcher (a pivot)

This document previously specified a **launcher** (`basecamp claude`) that owned the `claude` invocation and **fully replaced the system prompt** via `--system-prompt-file`. That design is **abandoned** in favor of a **Claude Code plugin bundling a stdio MCP context server** ([`claude/README.md`](../../claude/README.md)).

Why the pivot:

- **Less to own.** A plugin loads through Claude Code's native mechanisms (`--plugin-dir` / marketplace); it does not wrap or replace the `claude` invocation, and it sheds the launcher, the per-session settings assembly, and the whole frozen-prompt problem the launcher created.
- **Native channel for dynamic context.** Claude Code injects an MCP server's `instructions` field into the system prompt at session start (2KB, then resources carry the bulk). That is enough to deliver project awareness without seizing the *entire* prompt — so basecamp keeps Claude Code's own tool/safety/output guidance instead of re-authoring and maintaining it.
- **Static vs. dynamic split.** Static assets (skills, hooks, commands, agents) are native plugin components; only *computed per-session* context needs the MCP server. See [`claude/README.md`](../../claude/README.md) for the full inventory and the Tier 0–2 rollout.

One insight from the old design survives the pivot: **enforcement lives in a `PreToolUse` hook, not the prompt** — correctness never depended on prompt freshness ([`guards.ts`](../../pi/core/project/workspace/guards.ts)). Worktrees ride Claude Code's native machinery (`-w`, `EnterWorktree`, `isolation: worktree`, auto-cleanup); how the lifecycle is surfaced is a delivery detail in [`claude/README.md`](../../claude/README.md).

## 4. Retired vs. delivered

**Retired (not ported):** the hub daemon and swarm intercommunication (ask/message/handles), workstream SQLite, the companion dashboard/TUI, full-system-prompt replacement, the launcher, and Pi-specific plumbing (global-registry, session-state, catalog). Cross-session orchestration is available only as an *optional* daemon-backed Tier-2 MCP layer, never a requirement.

**Delivered (the plugin — see [`claude/README.md`](../../claude/README.md)):** dynamic project context via a stdio MCP server (related dirs + custom context + Logseq resources); native skills, hooks, commands, and specialist agents; a `SessionStart` setup hook; an optional `PreToolUse` bash/path guard.

## 5. Prior art (recover, don't rebuild)

basecamp **was** a Claude Code launcher-plus-plugins app before it migrated to Pi at commit `6674cc4` ("feat: migrate to pi extension architecture"); the full pre-migration implementation is recoverable at `6674cc4^`. The launcher itself is superseded (§3), but the **bundled plugins** remain a direct template for the plugin approach — `bc-collab`, `bc-cursor`, `bc-eng`, `bc-git-protect` (the bash-reviewer analog), `bc-gpg-check`, `bc-private`, `companion`. Recover the plugin components and the `.env` / `BASECAMP_*` injection logic (`build_session_settings`); re-derive project detection, which moved to TypeScript.

## 6. Roadmap

Delivery phases are the Tier 0–2 rollout in [`claude/README.md`](../../claude/README.md): Tier 0 (related dirs + context — the awareness MVP) → Tier 1 (Logseq repo-memory resources, read-only) → Tier 2 (optional local orchestration tools: worktrees, workstreams, cross-session messaging, Herdr, BigQuery), with a parallel native track (port the engineering skills, add the `copilot` skill, wire the `SessionStart` setup hook).
