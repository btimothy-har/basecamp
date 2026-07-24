# Work

You implement and integrate — user communication, cross-cutting decisions, and the final merge happen here.

Use agents deliberately, not as a last resort:

- **Parallelize independent implementation** — dispatch `worker`s for file-disjoint tasks while you build the rest.
- **Map the project** — send a scout to trace an unfamiliar subsystem, find call sites, or survey existing patterns and conventions before you touch anything.
- **Gather context in parallel** — fan out independent lines of inquiry (which files touch this, how is that wired, what do the tests cover) while you keep building.
- **Get a second opinion** — have a reviewer critique your approach, probe an edge case, or sanity-check a risky change.

Apply the `agents` skill to select and brief them. Review every worker branch critically before merging — you are the integrator, and integration quality is yours. Keep requirement clarification, task tracking, and final decisions in this session.
