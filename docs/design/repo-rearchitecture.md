# Repo Re-Architecture — Artifact-Oriented Layout (historical)

**Status:** HISTORICAL RECORD (executed 2026-07; largely superseded by the Pi deprecation) · **Scope:** why the repo top level is organized by *shipped artifact* and the Python is one ordinary package · **Related:** [claude-code-compatibility](./claude-code-compatibility.md)

> **Update (2026-07, Pi deprecation complete).** This record described a repo that shipped **three** artifacts over one shared body of *bilingual domains* (a TypeScript Pi extension + a Python package + a reserved Claude launcher). The Pi extension and its Pi-legacy Python have since been **removed**; the repo now ships **two** artifacts — the Claude Code plugin (`claude/`) and the `basecamp` Python package (`src/basecamp/`) — and the per-domain TypeScript innards this doc catalogued are gone. What survives, and why this record is kept: the **artifact-oriented top level** and the **one ordinary `src/basecamp/` package** decided here are still the repo's shape. The current layout is in [AGENTS.md](../../AGENTS.md); this doc is the rationale behind the `src/basecamp/` centralization.

---

## 1. The organizing insight

The repo is organized by the **artifact it ships**, not by feature or by language. Each artifact is an *assembly* — none owns a separate pile of code that the others don't touch. At the time of this pass there were three artifacts over one shared set of domains; after the Pi deprecation there are two:

| Artifact | What it is | Assembled from |
|---|---|---|
| The Claude Code plugin | native plugin components + thin shims | `claude/` |
| The `basecamp` Python package | the CLI, launcher, MCP server, hooks, and hub daemon | `src/basecamp/` |
| ~~The Pi extension~~ | ~~the TypeScript extension loaded into a Pi session~~ | ~~`pi/` (removed)~~ |

The top level names each artifact directly (`claude/`, `src/basecamp/`) plus root config and scaffolding (`docs/`, `tests/`, `migrations/`), so the top level reads as *what the repo ships*.

## 2. Decisions that still hold

Two decisions from this pass survive the Pi deprecation and remain load-bearing:

- **Top level by artifact.** Name each root for what it *is* (`claude/`, `src/basecamp/`), rather than exposing a flat pile of feature directories or burying everything one level down under a single `src/`.
- **Centralized Python — one ordinary package.** `src/basecamp/` is a single src-layout package; `import basecamp.<domain>` resolves to `src/basecamp/<domain>/`. This pass deleted the earlier PEP 420 namespace-portion machinery (per-domain `py/` roots reassembled at install time, a `check-namespace` guard, a multi-entry `sys.path` in `install.py`) — that apparatus existed only to support scattering the package across many directories, and centralizing removed the reason for it.

The `pyproject.toml` build config reflects this: `packages = ["src/basecamp"]`, `dev-mode-dirs = ["src"]`, no portion list.

## 3. What was removed with Pi

The bulk of the original record — the per-domain TypeScript innards (the `pi/<domain>/` two-layer "adapters vs. features" grouping, the `#<domain>/*` import-boundary contract, the `[tool]`/`[widget]`/`[hook]` surface tagging, and the ten domain-by-domain layout maps) — described the Pi extension's internal structure. That extension is gone, and with it the TypeScript toolchain (`package.json`, `tsconfig.json`, `biome.json`), the import-boundary and file-length lint scripts (`scripts/`), and the Pi-side domains. The Python domains those maps paired with (`core`, `workspace`, and the former `swarm`/`companion`) were correspondingly slimmed: the swarm daemon and companion TUI were deleted, leaving `core` and `workspace` beside the Claude-era `mcp`, `hooks`, `claude`, and `hub.claude` subpackages.

The design record for that removal is the Pi deprecation itself; the current package layout, dev workflow, and architecture decisions live in [AGENTS.md](../../AGENTS.md).
