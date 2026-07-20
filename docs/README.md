# docs/

Reference material for basecamp. **This is not a workspace for routine work.**

## `design/` — historical design archive

`design/` holds the design records for past structural changes to the repo: the rationale, alternatives, and decisions behind work that has largely already shipped. Each file is a point-in-time record — it carries its own status header and **may lag the current code**. Read them for background on *why* a subsystem is shaped the way it is; the authoritative current-state guide is always `AGENTS.md` and the code itself.

These are an **archive, not a template.** Do not create a new design or plan document here as part of normal work:

- Planning is done through the `plan()` tool. The approved plan is the artifact — it is handed to the implementer, not written into `docs/`.
- Durable architecture rationale belongs in `AGENTS.md` (the *Architecture Decisions* section), next to the guidance agents actually read.
- Most changes need no document at all — the code, its tests, and `AGENTS.md` are the record.

Add a new design record only when explicitly asked to.
