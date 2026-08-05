# Your first session

Launch sessions with plain Pi from the repo or subdirectory you want to work in. Basecamp detects the git repository root and loads the matching project when its `repo_root` is configured.

```bash
cd ~/GitHub/web-app
pi                         # Detects project by repo_root

cd ~/GitHub/web-app/src/api
pi                         # Also detects the same project from the git root

pi --style advisor         # Optional working style override
```

If the launch cwd's git root does not match a configured `repo_root`, Basecamp starts an unprojected Pi session.

## Managing projects

Project configuration is managed through the projects menu:

```bash
basecamp projects
```

Use it to list, add, edit, or remove configured projects. See [projects.json reference](../configuration/projects.md) for the full schema.
