# 10 — Cleanup

## Goal

Remove deprecated plugins, update documentation, and verify the complete migration.

## Deletions

### Remove old plugin directories

```bash
rm -rf plugins/companion/     # Fully replaced by extension/
rm -rf plugins/pi-eng/         # Extension + skills moved to extension/
rm -rf plugins/pi-git-protect/ # Extension moved to extension/src/git-protect.ts
rm -rf plugins/pi-collab/      # Skills moved to extension/skills/
rm -rf plugins/cursor/         # No longer needed (Cursor IDE integration, not pi)
rm -rf plugins/private/        # Personal tools, safe to delete
```

### Remove empty `plugins/` directory

If no plugins remain:

```bash
rmdir plugins/
```

### Update `.gitignore`

Remove any `plugins/private/` gitignore entries if present. Add `extension/node_modules/` if any npm deps are added later.

## Documentation Updates

### `CLAUDE.md` (repo root)

Update the repo map to reflect the new structure:

- Remove all `plugins/` entries
- Add `extension/` section:

```
extension/                      # Pi extension package
├── package.json                # Pi package manifest
├── src/
│   ├── index.ts                # Extension entry point
│   ├── lifecycle.ts            # Session init, env setup, context injection
│   ├── git-protect.ts          # Destructive git/gh command guards
│   ├── observer.ts             # Observer pipeline triggers
│   ├── messaging.ts            # Inter-agent inbox
│   ├── workers.ts              # Worker close-on-exit
│   └── nudges.ts               # Skill nudging on file edits
├── skills/                     # 18 skills (engineering, collaboration, session management)
└── prompts/                    # Prompt templates
```

Update the **Plugin System** section in Architecture Decisions:
- Remove references to Claude Code's plugin format
- Describe the pi extension approach
- Note that `bc-companion` is no longer bundled — replaced by the extension

Update any references to `CLAUDE_COMMAND` → `PI_COMMAND`.

### `core/CLAUDE.md`

Update if it references companion plugin, plugin loading, or Claude CLI specifics.

### `observer/CLAUDE.md`

Verify no broken references to companion hook scripts.

## Verification Checklist

### Extension loads cleanly

```bash
cd /path/to/project
pi -e /path/to/basecamp/extension
```

- [ ] No load errors
- [ ] `basecamp: repo=<name>` notification appears
- [ ] 18 skills listed in `/skill:` autocomplete

### Git protection works

- [ ] `git push --force` → blocked
- [ ] `git push --delete main` → blocked
- [ ] `git clean -f` → blocked
- [ ] `gh pr merge` → blocked
- [ ] `gh issue list` → allowed
- [ ] `gh pr view` → allowed

### Session lifecycle works

- [ ] Scratch directories created
- [ ] `GIT_REPO` env var set
- [ ] Project context injected (when `BASECAMP_CONTEXT_FILE` set)

### Observer integration works (when enabled)

- [ ] Ingest triggered on compaction
- [ ] Ingest triggered on shutdown
- [ ] Pre-ingest on dispatch commands

### Inter-agent messaging works

- [ ] `.immediate` files consumed after tool calls
- [ ] `.msg` files consumed at agent end
- [ ] Messages appear in conversation

### Worker lifecycle works

- [ ] Worker close fires on shutdown (when `BASECAMP_WORKER_NAME` set)

### Launch integration works

- [ ] `basecamp launch <project>` starts pi (not claude)
- [ ] Extension loaded automatically
- [ ] System prompt applied
- [ ] BASECAMP_* env vars available

### No orphaned references

```bash
# Should return nothing after cleanup:
grep -r "companion" core/src/ --include="*.py" -l
grep -r "pi-eng\|pi-git-protect\|pi-collab" . --include="*.py" --include="*.ts" --include="*.json" -l
grep -r "CLAUDE_COMMAND" core/src/ --include="*.py" -l
grep -r "plugin-dir" core/src/ --include="*.py" -l
```

## Acceptance Criteria

- [ ] No `plugins/` directory exists (or is empty)
- [ ] All documentation updated
- [ ] Full verification checklist passes
- [ ] `git status` shows clean deletions and additions
- [ ] Tests pass: `uv run pytest`
