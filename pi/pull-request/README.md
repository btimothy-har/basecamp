# pull-request

A primary-only feature domain that exposes `/pull-request [additional instructions]` as a thin prompt command and `pull-request` as its matching model-invocable skill. The command unconditionally directs the agent to load and execute the skill; the skill is authoritative for PR preparation and publication through completed CI and the user-selected draft or ready stopping state. It never merges, closes, or approves a PR.

## Flow

- Draft-only title/body requests stop before GitHub mutation.
- Publication requests inspect the branch, merge-base diff, repository guidance, template, existing PR, and validation evidence.
- New PRs always open as drafts through existing human-gated `git` and `gh` commands.
- Branch-caused CI failures are fixed and rechecked while the PR remains draft.
- Green CI requires an explicit leave-draft or mark-ready decision; absence of ready intent stops at the green draft.
- Ready PRs follow only repository-required reviews, with every comment verified before it is fixed, contested, replied to, or resolved.

## Layout

- `index.ts` — exposes the prompt command and skill through `resources_discover` in primary sessions only.
- `prompts/pull-request.md` — thin command wrapper that loads and executes the skill with optional additional instructions.
- `skills/pull-request/SKILL.md` — authoritative drafting, publication, CI, readiness, and review lifecycle.
- `tests/index.test.ts` — primary/subagent discovery and lifecycle contract coverage.

The domain registers no custom tool and adds no new hard gate. GitHub publication runs through the existing bash reviewer, whose routing is LLM-judgment plus human confirmation rather than a guaranteed block; the skill also hard-stops at the green draft when no interactive UI can confirm readiness.
