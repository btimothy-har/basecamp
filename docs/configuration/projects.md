# projects.json reference

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

Root `~/.pi/basecamp/config.json` holds installer-owned metadata (`install_dir`, `installed_modules`) and per-repo worktree `environments` (see [Worktree environments](worktree-environments.md)); it does not contain project definitions.

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in `basecamp projects` listings |
| `working_style` | No | Loads matching working style prompt (see below) |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/workspace/context/{name}.md` for project context |

Existing local config files with the older project directory schema are migrated to `repo_root` and `additional_dirs` by setup/projects flows.
