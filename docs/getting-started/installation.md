# Installation

## Requirements

- **[uv](https://docs.astral.sh/uv/)**: Python package manager; installs and manages Python 3.12+
- **[pi](https://github.com/earendil-works/pi)**: the AI coding agent harness that basecamp extends
- **Git**: for project detection and isolated worktrees

Optional, for `/diff` (reviewing changes in [hunk](https://github.com/modem-dev/hunk)):

- **[hunk](https://github.com/modem-dev/hunk)**: `npm i -g hunkdiff`, `brew install hunk`, or nixpkgs
- **[Herdr](https://herdr.dev)**: a running Herdr session

`/diff` needs both; without them it reports what is missing and does nothing.

## Install

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py
```

This installs the `basecamp` Python tool and registers the Pi extension from the repo root.

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
