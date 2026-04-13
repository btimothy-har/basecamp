# 08 — Move All Skills

## Goal

Move all 18 skills from `plugins/pi-eng/skills/`, `plugins/pi-collab/skills/`, and `plugins/companion/skills/` into `extension/skills/`.

## Source Skills

### From `plugins/pi-eng/skills/` (13 skills)

| Skill | Has References |
|-------|---------------|
| `python-development/` | Yes — 10 reference .md files |
| `sql/` | Yes — 5 reference .md files |
| `code-review/` | Yes — 2 reference .md files |
| `data-warehousing/` | Yes — 5 reference .md files |
| `code-documentation/` | No |
| `code-simplification/` | No |
| `context-gatherer/` | No |
| `marimo/` | No |
| `pr-comments/` | No |
| `pr-walkthrough/` | No |
| `pull-request/` | No |
| `security-review/` | No |
| `test-review/` | No |

### From `plugins/pi-collab/skills/` (2 skills)

| Skill | Notes |
|-------|-------|
| `discovery/` | Requirements gathering, interview techniques |
| `gh-issue/` | GitHub issue capture |

### From `plugins/companion/skills/` (3 skills)

| Skill | Notes |
|-------|-------|
| `dispatch/` | Worker dispatch — references `worker create --dispatch` |
| `recall/` | Semantic memory search — references `recall` CLI |
| `workers/` | Worker management — references `worker ask/send/inbox/list` |

## Process

### 1. Copy skill directories

```bash
# From pi-eng (with references/)
cp -r plugins/pi-eng/skills/* extension/skills/

# From pi-collab
cp -r plugins/pi-collab/skills/* extension/skills/

# From companion
cp -r plugins/companion/skills/* extension/skills/
```

### 2. Verify names match directories

Per the Agent Skills spec, `name` in frontmatter must match the parent directory name. Verify all 18 skills comply. Current names are correct — no renames needed.

### 3. Remove `.gitkeep`

Delete `extension/skills/.gitkeep` now that the directory has real content.

### 4. Verify no broken references

Skills with `references/` subdirectories use relative paths in their SKILL.md. Since we're preserving directory structure, all relative paths remain valid:

```markdown
See [the reference guide](references/REFERENCE.md) for details.
```

### 5. Check for script references

Some skills reference executable scripts (e.g., the companion dispatch skill references `worker create`). These are CLI commands (`basecamp worker`, `recall`), not script files within the skill directory — no path updates needed.

## Target Structure

```
extension/skills/
├── code-documentation/
│   └── SKILL.md
├── code-review/
│   ├── SKILL.md
│   └── references/
│       ├── DIMENSIONS.md
│       └── SCORING.md
├── code-simplification/
│   └── SKILL.md
├── context-gatherer/
│   └── SKILL.md
├── data-warehousing/
│   ├── SKILL.md
│   └── references/
│       ├── DIMENSIONAL_MODELING.md
│       ├── DOCUMENTATION.md
│       ├── MATERIALIZATION.md
│       ├── MODEL_LAYERS.md
│       └── TESTING.md
├── discovery/
│   └── SKILL.md
├── dispatch/
│   └── SKILL.md
├── gh-issue/
│   └── SKILL.md
├── marimo/
│   └── SKILL.md
├── pr-comments/
│   └── SKILL.md
├── pr-walkthrough/
│   └── SKILL.md
├── pull-request/
│   └── SKILL.md
├── python-development/
│   ├── SKILL.md
│   └── references/
│       ├── BACKEND.md
│       ├── CODE_SMELLS.md
│       ├── CODE_STRUCTURE.md
│       ├── DATA_STRUCTURES.md
│       ├── ERROR_HANDLING.md
│       ├── NAMING.md
│       ├── PATTERNS.md
│       ├── TESTING.md
│       ├── TYPING.md
│       └── UV.md
├── recall/
│   └── SKILL.md
├── security-review/
│   └── SKILL.md
├── sql/
│   ├── SKILL.md
│   └── references/
│       ├── FORMATTING.md
│       ├── NULL_HANDLING.md
│       ├── PERFORMANCE_BIGQUERY.md
│       ├── PERFORMANCE_POSTGRES.md
│       └── QUERY_STRUCTURE.md
├── test-review/
│   └── SKILL.md
└── workers/
    └── SKILL.md
```

## Acceptance Criteria

- [ ] All 18 skill directories exist under `extension/skills/`
- [ ] Each SKILL.md has valid frontmatter with `name` matching directory name
- [ ] All `references/` subdirectories preserved with contents
- [ ] `extension/skills/.gitkeep` removed
- [ ] `pi -e ./extension` shows all 18 skills available (check with `/skill:` autocomplete)
- [ ] No duplicate skill names
