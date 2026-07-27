---
name: copilot
description: Page schema and write rules for the Logseq repo memory this session curates — journals for live state, work dossiers for durable context, the repo cockpit as anchor. Load before writing or restructuring repo memory.
---

# Repo memory

Repo memory is three artifacts. Each answers a different question, and mixing them is what makes memory drift.

| Artifact | Answers | Write mode |
|---|---|---|
| `journals/YYYY_MM_DD.md` | What happened that day | Append |
| `pages/work__<org>__<repo>__<slug>.md` | Why this work exists and what has been settled | Edit, rarely |
| `pages/repo__<org>__<repo>.md` | Repo-level context worth carrying between sessions | Authored, sparse |

Before your first write in a graph, open an existing page and match its conventions — indentation and whether page properties sit bare at the top of the file or inside a first `- ` block both vary by Logseq version.

## Journals — live state

Everything that changes goes here: progress, blockers hit and cleared, priority shifts, workstream launches, things tried and abandoned.

Nest repo-first. The graph is shared across every repo, so a top-level heading collides with other repos on the same day.

```markdown
- ## [[repo__btimothy-har__basecamp]]
	- ### [[work__btimothy-har__basecamp__quiet-heron-drift]] · `gentle-marten-tide`
		- Reframed repo memory around journals; dropped the dossier status property.
		- CI red on #318 — root cause is the boundary check, not the schema change.
	- ### [[work__btimothy-har__basecamp__amber-finch-lane]]
		- Shaped scope; no workstream staged yet.
```

The dossier reference leads and the workstream slug qualifies it. Work has a dossier before it has a workstream, and one dossier can back several workstreams — sibling blocks sharing a dossier reference read correctly, slug-first headings do not.

Record events, never workstream status. A journal page is fixed to its day, so writing "closed" freezes a fact that can change tomorrow — a workstream can be reopened. The daemon owns lifecycle; ask `list_workstreams` when you need current status.

## Work dossier — durable context

Only what stays true. If a fact will be wrong next week, it belongs in a journal.

```markdown
type:: work-dossier
repo:: [[repo__btimothy-har__basecamp]]

- ## Objective
	- Give copilot a defined structure for repo memory so dossiers stop drifting.
- ## Context
	- Copilot is sole writer of repo memory but was never told the format.
	- Page names are flat, so there is no namespace tree to navigate by.
- ## Decisions
	- 2026-07-27 — Dossier holds durable context only; live state lives in journals.
	- 2026-07-27 — Cockpit is an anchor, not a work record.
```

Those three sections and those two properties are the whole schema. Do not add `status::`, `priority::`, `updated::`, or `workstreams::` — each is live state or a third copy of something the journals and the daemon already answer. Do not add a done-signal section; that belongs to the workstream record.

You never write the dossier's timeline. Because journal blocks reference the dossier, Logseq assembles every mention into the page's linked references. A derived timeline cannot fall out of date, which is the entire reason state stays out of this page.

A decision legitimately lands twice: the journal records that it was made that day, the dossier records that it now stands.

## Repo cockpit — anchor

Sparse by design. It holds only what would be wrong to commit to the repository: standing priorities, external dependencies, people, why this repo matters right now.

```markdown
type:: repo-cockpit
repo:: btimothy-har/basecamp

- ## Notes
	- Prompt-architecture work is the standing priority; infra changes wait behind it.
	- Pi upstream ships breaking extension-API changes roughly monthly.
```

It is not an index — the dossier glob already serves you and a query serves the user. It is not a status board — that is what recent journals are for. If it starts reading like `AGENTS.md`, the content is in the wrong place.

It earns its place even near-empty: journal blocks nest under its reference, so its linked references are the repo's timeline.

## Writing

Propose before writing. Show the actual Logseq-formatted blocks and get approval; when the user edits your proposal, use their version verbatim.

Append to journals. Edit dossiers in place, and only when durable framing actually changed. Never rewrite a journal entry to reflect what you now know — write today's correction as today's block.

Capture durable coordination value, not raw transcripts, dispatch receipts, or unverified claims. Only record what actually happened.

In read-only sessions, prepare the same proposals and hand them to the user instead of writing.

**Never write `title::`.** It is Logseq's filename-to-display mapping for names containing reserved characters. Repo memory page names are already filename-safe, and basecamp resolves pages by filename — a `title::` property can desynchronize the two.

Property values are only linked when written as explicit wikilinks (`[[a]], [[b]]`); comma-separated plain text is not, in current Logseq. Link deliberately, and do not link a value that has no page.
