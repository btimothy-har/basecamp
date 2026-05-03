# Skills Reference

Skills are self-contained capability packages following the [Agent Skills standard](https://agentskills.io/specification). They implement progressive disclosure — only descriptions are in context at startup, full instructions load on-demand.

## Structure

```
my-skill/
├── SKILL.md              # Required: frontmatter + instructions
├── scripts/              # Helper scripts
│   └── process.sh
├── references/           # Detailed docs loaded on-demand
│   └── api-reference.md
└── assets/
    └── template.json
```

## SKILL.md Format

```markdown
---
name: my-skill
description: What this skill does and when to use it. Be specific — this determines when the agent loads it.
---

# My Skill

## Setup

Run once before first use:
\`\`\`bash
cd /path/to/skill && npm install
\`\`\`

## Usage

\`\`\`bash
./scripts/process.sh <input>
\`\`\`

See [the reference guide](references/REFERENCE.md) for details.
```

Use **relative paths** from the skill directory for all references.

## Frontmatter

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Max 64 chars. Lowercase `a-z`, `0-9`, hyphens. Must match parent directory. |
| `description` | Yes | Max 1024 chars. What the skill does and when to use it. |
| `license` | No | License name or reference |
| `compatibility` | No | Max 500 chars. Environment requirements. |
| `metadata` | No | Arbitrary key-value mapping |
| `allowed-tools` | No | Space-delimited pre-approved tools (experimental) |
| `disable-model-invocation` | No | When `true`, hidden from system prompt — users must use `/skill:name` |

### Name Rules

- 1-64 characters
- Lowercase letters, numbers, hyphens only
- No leading/trailing hyphens, no consecutive hyphens
- Must match parent directory name

Valid: `pdf-processing`, `data-analysis`, `code-review`
Invalid: `PDF-Processing`, `-pdf`, `pdf--processing`

### Description Best Practices

The description determines when the agent loads the skill. Be specific.

**Good:**
```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents.
```

**Poor:**
```yaml
description: Helps with PDFs.
```

Include keywords that help the agent match tasks to the skill.

## Locations

| Location | Scope | Discovery |
|----------|-------|-----------|
| `~/.pi/agent/skills/` | Global | Directories with `SKILL.md` + root `.md` files |
| `~/.agents/skills/` | Global | Directories with `SKILL.md` only (root `.md` ignored) |
| `.pi/skills/` | Project | Directories with `SKILL.md` + root `.md` files |
| `.agents/skills/` | Project (walks up to repo root) | Directories with `SKILL.md` only |
| Packages | Via `pi.skills` in `package.json` | Recursive `SKILL.md` discovery |

## Invocation

- `/skill:name` — explicitly load and execute
- `/skill:name args` — load with arguments (appended as `User: <args>`)
- Automatic — agent loads when task matches description

Toggle skill commands via `/settings` or `enableSkillCommands` in `settings.json`.

## Validation

- Missing description → skill not loaded
- Name mismatch, invalid chars, length issues → warning, still loaded
- Name collisions → warning, first found wins
- Unknown frontmatter fields → ignored

## Design Tips

- **Progressive disclosure** — keep `SKILL.md` focused on usage; put detailed docs in `references/`
- **Specific descriptions** — include keywords, mention file types, use cases
- **Relative paths** — always reference scripts and assets relative to the skill directory
- **Self-contained** — include setup instructions, don't assume dependencies exist
