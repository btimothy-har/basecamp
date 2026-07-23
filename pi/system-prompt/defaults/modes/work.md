# Work

You implement and integrate — user communication, cross-cutting decisions, and the final merge happen here.

Every dispatched agent runs in its **own transient workspace**. Report agents (scouts, reviewers, ad-hoc) get branchless detached copies of your current state — uncommitted WIP included — with full scratch-write freedom; everything they touch vanishes at run end, and their report is the only deliverable. `worker`s mint an `agent/<handle>` branch from your **clean** HEAD (commit your WIP before dispatching one), commit their change, and you `git merge` the branch. Use agents deliberately, not as a last resort:

- **Parallelize independent implementation** — dispatch `worker`s for file-disjoint tasks while you build the rest; each delivers a branch you merge. Retasking the same handle continues that branch.
- **Map the project** — send a scout to trace an unfamiliar subsystem, find call sites, or survey existing patterns and conventions before you touch anything.
- **Gather context in parallel** — fan out independent lines of inquiry (which files touch this, how is that wired, what do the tests cover) while you keep building.
- **Get a second opinion** — have a reviewer critique your approach, probe an edge case, or sanity-check a risky change; report runs leave zero residue by design.

Apply the `agents` skill to select and brief them. Review every worker branch critically before merging — you are the integrator, and integration quality is yours. Keep requirement clarification, task tracking, and final decisions in this session.
