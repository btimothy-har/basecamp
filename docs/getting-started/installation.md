# Installation

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — Python package manager; installs and manages Python 3.12+
- **[pi](https://github.com/earendil-works/pi)** — the AI coding agent harness that basecamp extends
- **Git** — for project detection and isolated worktrees

Optional, for `/diff` (reviewing changes in [hunk](https://github.com/modem-dev/hunk)):

- **[hunk](https://github.com/modem-dev/hunk)** — `npm i -g hunkdiff`, `brew install hunk`, or nixpkgs
- **[Herdr](https://herdr.dev)** — a running Herdr session

`/diff` needs both; without them it reports what is missing and does nothing.

## Install

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py           # interactive (prompts for editable mode)
uv run install.py -e        # editable (recommended for development)
uv run install.py --no-editable
```

This installs the Python tool `basecamp`, prompts for optional Basecamp Pi package groups, and saves installer metadata to `~/.pi/basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, create workspace dirs, create default project config
```

If `basecamp` isn't in your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Upgrading

```bash
uv tool upgrade basecamp
```

## Uninstalling

```bash
uv tool uninstall basecamp
```
