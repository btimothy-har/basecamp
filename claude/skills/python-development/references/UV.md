# UV Package Manager

Fast Python package manager. Use `uv run` to execute Python; dependencies install automatically.

## Complete Command Reference

```bash
# Project workflow
uv init [PATH]              # Initialize project (creates pyproject.toml, .python-version)
uv add PACKAGE              # Add dependency
uv add --dev PACKAGE        # Add dev dependency
uv remove PACKAGE           # Remove dependency
uv sync                     # Install all dependencies from lockfile
uv lock                     # Update uv.lock

# Execution (auto-creates venv, installs deps)
uv run python script.py     # Run Python script
uv run pytest               # Run CLI tool
uv run --python 3.12 CMD    # Run with specific Python version

# Python management
uv python install 3.12      # Install Python version
uv python pin 3.12          # Set project Python version
uv python list              # List available versions
```

## Standalone Scripts with Inline Dependencies

For scripts that don't need a full project, use inline metadata:

```python
# /// script
# dependencies = [
#   "requests>=2.31.0",
#   "pandas>=2.0.0",
# ]
# requires-python = ">=3.12"
# ///

import requests
import pandas as pd

# script code...
```

Run directly: `uv run script.py` — uv reads the metadata and installs dependencies automatically.

## Project Configuration (pyproject.toml)

```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "ruff>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=7.4.0",
]

[tool.uv.sources]
# Custom sources
my-package = { git = "https://github.com/user/repo.git" }
```

## Common Patterns

### Adding Dependencies

```bash
uv add requests                           # Latest version
uv add "django>=4.0,<5.0"                 # Version constraint
uv add --dev pytest ruff                  # Dev dependencies
uv add git+https://github.com/user/repo   # From git
uv add -e ./local-package                 # Editable local package
```

### Syncing and Locking

```bash
uv sync                     # Install from pyproject.toml + uv.lock
uv sync --frozen            # Exact versions from lockfile (CI use)
uv sync --all-extras        # Include optional dependency groups
uv lock                     # Generate/update uv.lock
uv lock --upgrade           # Upgrade all dependencies in lock
```

### Virtual Environments

```bash
uv venv                     # Create .venv
uv venv --python 3.12       # With specific Python
```

Note: Prefer `uv run` over manual venv activation.

## CI/CD (GitHub Actions)

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v2
    with:
      version: "0.9.x"    # Pin uv version for reproducibility
      enable-cache: true
  - run: uv python install 3.12
  - run: uv sync --frozen --all-extras
  - run: uv run pytest
```

## Docker

```dockerfile
FROM python:3.12-slim

# Pin uv version for reproducibility
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
CMD ["uv", "run", "python", "app.py"]
```

## Workspace (Monorepo)

```toml
# Root pyproject.toml
[tool.uv.workspace]
members = ["packages/*"]
```

```bash
uv sync                           # Install all workspace packages
uv add --path ./packages/pkg-a    # Add workspace dependency
```

## Key Behaviors

- `uv run` auto-creates venv and installs dependencies if missing
- `uv.lock` should be committed for reproducible builds
- `.python-version` file pins the project's Python version
- Global cache at `~/.cache/uv` (Linux) / `~/Library/Caches/uv` (macOS)
- Use `--frozen` in CI to enforce exact lockfile versions
- Pin uv version in CI/Docker — uv evolves rapidly
