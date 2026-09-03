# Pull-Request Skill

A primary-only feature domain that exposes `/pull-request [additional instructions]` as a thin action prompt and `pull-request` as its matching model-invocable guidance skill. The command unconditionally directs the agent to load and apply the skill; the skill is authoritative for handling PRs across drafting, publication, CI, readiness, and requested reviews. It never merges or closes a PR and submits an approving review only when the user explicitly authorizes that approval action.

## Flow

- Draft-only title/body requests stop before GitHub mutation.
- Publication requests inspect the branch, merge-base diff, repository guidance, template, existing PR, and validation evidence.
- New PRs always open as drafts through existing human-gated `git` and `gh` commands.
- Branch-caused CI failures are fixed and rechecked while the PR remains draft.
- Green CI requires an explicit leave-draft or mark-ready decision; absence of ready intent stops at the green draft.
- Ready PRs follow only repository-required reviews, with every comment verified before it is fixed, contested, replied to, or resolved.
- Approving reviews require explicit user authorization for approval; preparing or updating a PR, marking it ready, posting comments, or clearing feedback does not imply it.

## Layout

- `index.ts`: exposes the action prompt and guidance skill through `resources_discover` in primary sessions only.
- `prompts/pull-request.md`: thin command wrapper that loads and applies the skill with optional additional instructions.
- `skills/pull-request/SKILL.md`: authoritative guidance for drafting, publication, CI, readiness, and requested reviews.

The domain registers no custom tool and adds no deterministic hard gate. GitHub publication runs through the existing bash reviewer, whose model gate denies unrequested approving reviews and routes explicitly authorized approvals for human confirmation; the skill also hard-stops at the green draft when no interactive UI can confirm readiness.
