# pull-request

A primary-only feature domain that exposes the model-invocable `pull-request` skill. It owns PR preparation and publication through completed CI and the user-selected draft or ready stopping state; it never merges, closes, or approves a PR.

## Flow

- Draft-only title/body requests stop before GitHub mutation.
- Publication requests inspect the branch, merge-base diff, repository guidance, template, existing PR, and validation evidence.
- New PRs always open as drafts through existing human-gated `git` and `gh` commands.
- Branch-caused CI failures are fixed and rechecked while the PR remains draft.
- Green CI requires an explicit leave-draft or mark-ready decision; absence of ready intent stops at the green draft.
- Ready PRs follow only repository-required reviews, with every comment verified before it is fixed, contested, replied to, or resolved.

## Layout

- `index.ts` — exposes the skill through `resources_discover` in primary sessions only.
- `skills/pull-request/SKILL.md` — drafting, publication, CI, readiness, and review lifecycle.
- `tests/index.test.ts` — primary/subagent discovery and lifecycle contract coverage.

The domain registers no custom tool and adds no new hard gate. GitHub publication runs through the existing bash reviewer, whose routing is LLM-judgment plus human confirmation rather than a guaranteed block; the skill also hard-stops at the green draft when no interactive UI can confirm readiness.
