# Packages Reference

Pi packages bundle extensions, skills, prompt templates, and themes for distribution via npm or git.

## Creating a Package

Add a `pi` manifest to `package.json`:

```json
{
  "name": "my-pi-package",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extensions"],
    "skills": ["./skills"],
    "prompts": ["./prompts"],
    "themes": ["./themes"]
  }
}
```

Paths are relative to package root. Arrays support glob patterns and `!exclusions`.

### Without Manifest

Auto-discovers from conventional directories: `extensions/`, `skills/`, `prompts/`, `themes/`.

### Gallery Metadata

```json
{
  "pi": {
    "video": "https://example.com/demo.mp4",
    "image": "https://example.com/screenshot.png"
  }
}
```

## Dependencies

- **Runtime deps** → `dependencies` in `package.json` (installed by `npm install` on setup)
- **Pi core packages** → `peerDependencies` with `"*"`:
  - `@mariozechner/pi-ai`
  - `@mariozechner/pi-agent-core`
  - `@mariozechner/pi-coding-agent`
  - `@mariozechner/pi-tui`
  - `@sinclair/typebox`
- **Other pi packages** → `dependencies` + `bundledDependencies`, reference via `node_modules/` paths

```json
{
  "peerDependencies": {
    "@mariozechner/pi-coding-agent": "*",
    "@sinclair/typebox": "*"
  },
  "dependencies": {
    "shitty-extensions": "^1.0.1"
  },
  "bundledDependencies": ["shitty-extensions"],
  "pi": {
    "extensions": ["extensions", "node_modules/shitty-extensions/extensions"]
  }
}
```

## Installing Packages

```bash
pi install npm:@foo/bar@1.0.0     # npm, pinned version
pi install npm:@foo/bar            # npm, latest
pi install git:github.com/user/repo@v1  # git with ref
pi install https://github.com/user/repo  # raw URL
pi install /path/to/local/package  # local path

pi remove npm:@foo/bar
pi list                            # show installed
pi update                          # update non-pinned
pi config                          # enable/disable resources
```

Use `-l` for project-local installs (writes to `.pi/settings.json`).

## Quick Test

```bash
pi -e npm:@foo/bar     # install to temp dir for this run only
pi -e git:github.com/user/repo
```

## Package Filtering

```json
{
  "packages": [
    "npm:simple-pkg",
    {
      "source": "npm:my-package",
      "extensions": ["extensions/*.ts", "!extensions/legacy.ts"],
      "skills": [],
      "prompts": ["prompts/review.md"]
    }
  ]
}
```

- Omit a key → load all of that type
- `[]` → load none
- `!pattern` → exclude
- `+path` / `-path` → force include/exclude

## Scope & Deduplication

- Packages in both global and project settings → project wins
- Identity: npm name, git URL (without ref), or resolved absolute path
- Global installs → `~/.pi/agent/git/` or global npm
- Project installs → `.pi/git/` or `.pi/npm/`
