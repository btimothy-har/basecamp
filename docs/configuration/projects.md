# Projects

A basecamp project groups one or more repositories and gives them shared configuration — a working style, allowed directories, and project context. Basecamp detects the active project from the git root of the directory you launch Pi in.

## Defining projects

Projects are defined in `~/.pi/basecamp/workspace/projects.json`:

```json
{
  "version": 1,
  "projects": {
    "web-app": {
      "repo_root": "GitHub/web-app",
      "additional_dirs": [],
      "description": "Main web application",
      "working_style": "engineering"
    },
    "data-pipeline": {
      "repo_root": "GitHub/pipeline",
      "additional_dirs": ["GitHub/pipeline-config"],
      "description": "ETL pipeline and configuration",
      "working_style": "engineering",
      "context": "pipeline"
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in `basecamp projects` listings |
| `working_style` | No | Loads matching working style prompt |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/workspace/context/{name}.md` for project context |

Manage them with `basecamp projects` (list, add, edit, remove). Existing local config files with the older project directory schema are migrated to `repo_root` and `additional_dirs` by setup/projects flows.

Root `~/.pi/basecamp/config.json` holds installer-owned metadata (`install_dir`, `installed_modules`) and per-repo worktree `environments` (see [Worktree environments](worktree-environments.md)); it does not contain project definitions.

## Project context

Project context is extra prompt material basecamp loads for the active project. There are two ways to provide it:

- **`AGENTS.md` in the repo** — the default for single-repo projects. Put agent-facing context (conventions, gotchas, pointers to depth) at the repository root.
- **A context file** — for multi-repo projects needing shared cross-repo context. Set the `context` field to a file stem (no `.md`); basecamp loads `~/.pi/basecamp/workspace/context/{name}.md`. For example, `"context": "pipeline"` loads `~/.pi/basecamp/workspace/context/pipeline.md`.

Both are additive: when present, the configured context file and the repo's `AGENTS.md` are loaded together.
