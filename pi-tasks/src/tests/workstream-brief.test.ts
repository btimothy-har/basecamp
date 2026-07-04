import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildWorkstreamLaunchBrief, type WorkstreamLaunchBriefInput } from "../workstreams/brief.ts";

interface WorkstreamLaunchBriefInputOverrides {
	source?: Partial<WorkstreamLaunchBriefInput["source"]>;
	workstream?: Partial<WorkstreamLaunchBriefInput["workstream"]>;
	worktree?: Partial<WorkstreamLaunchBriefInput["worktree"]>;
}

function makeInput(overrides: WorkstreamLaunchBriefInputOverrides = {}): WorkstreamLaunchBriefInput {
	return {
		source: {
			dossierPath: "/repo/logseq/pages/Dossier.md",
			repoPagePath: "/repo/logseq/pages/Repo.md",
			...overrides.source,
		},
		workstream: {
			label: "broad-investigation",
			brief: "Investigate the launch workstream and improve the highest-value path.",
			constraints: "Stay within the launch-workstream scope.",
			...overrides.workstream,
		},
		worktree: {
			label: "bt/broad-investigation",
			path: "/worktrees/org/repo/bt/broad-investigation",
			branch: "bt/broad-investigation",
			...overrides.worktree,
		},
	};
}

function assertForbiddenPhrasesAbsent(brief: string): void {
	const forbiddenPhrases = [
		"copilot",
		"proactively report",
		"store raw transcripts",
		"raw transcript",
		"launch JSON",
		"durable memory",
	];
	const normalized = brief.toLowerCase();

	for (const phrase of forbiddenPhrases) {
		assert.equal(normalized.includes(phrase.toLowerCase()), false, `forbidden phrase should be absent: ${phrase}`);
	}
}

describe("buildWorkstreamLaunchBrief", () => {
	it("renders broad workstream context and guardrails", () => {
		const brief = buildWorkstreamLaunchBrief(makeInput());

		assert.match(brief, /user-facing Herdr workstream surface/);
		assert.match(brief, /Workstream label: broad-investigation/);
		assert.match(brief, /Dossier: \/repo\/logseq\/pages\/Dossier\.md/);
		assert.match(brief, /Repo cockpit: \/repo\/logseq\/pages\/Repo\.md/);
		assert.match(brief, /Investigate the launch workstream and improve the highest-value path\./);
		assert.match(brief, /Worktree label: bt\/broad-investigation/);
		assert.match(brief, /Worktree path: \/worktrees\/org\/repo\/bt\/broad-investigation/);
		assert.match(brief, /Branch: bt\/broad-investigation/);
		assert.match(brief, /Work only in the assigned worktree/);
		assert.match(brief, /when it is broad, decompose it, prioritize the most valuable path/);
		assert.match(brief, /Do not write Logseq directly\./);
		assert.match(brief, /Do not push, create PRs, or merge unless explicitly asked\./);
		assert.match(brief, /Do not broadcast status outside this Herdr workstream/);
		assert.match(brief, /keep findings, changes, validation, and blocker context easy to summarize when asked/);
		assert.match(brief, /## Constraints\nStay within the launch-workstream scope\./);
		assertForbiddenPhrasesAbsent(brief);
	});

	it("omits constraints when a specific brief has no constraints", () => {
		const brief = buildWorkstreamLaunchBrief(
			makeInput({
				workstream: {
					label: "specific-slice",
					brief: "Implement only the agreed parser test update.",
					constraints: undefined,
				},
			}),
		);

		assert.match(brief, /Workstream label: specific-slice/);
		assert.match(brief, /Implement only the agreed parser test update\./);
		assert.match(brief, /Treat this brief as intentionally stretchable/);
		assert.match(brief, /when it is specific, execute that agreed slice directly/);
		assert.equal(brief.includes("## Constraints"), false);
		assert.equal(brief.includes("Stay within the launch-workstream scope."), false);
		assertForbiddenPhrasesAbsent(brief);
	});

	it("omits constraints when they are blank", () => {
		const brief = buildWorkstreamLaunchBrief(
			makeInput({
				workstream: {
					label: "blank-constraints",
					brief: "Handle the blank constraints case.",
					constraints: " \n\t ",
				},
			}),
		);

		assert.equal(brief.includes("## Constraints"), false);
		assertForbiddenPhrasesAbsent(brief);
	});

	it("handles missing repo page path cleanly", () => {
		const brief = buildWorkstreamLaunchBrief(
			makeInput({
				source: {
					dossierPath: "/repo/logseq/pages/Dossier.md",
					repoPagePath: undefined,
				},
			}),
		);

		assert.match(brief, /Dossier: \/repo\/logseq\/pages\/Dossier\.md/);
		assert.equal(brief.includes("Repo cockpit:"), false);
		assert.equal(brief.includes("undefined"), false);
		assert.match(brief, /Read the dossier as context when useful/);
		assertForbiddenPhrasesAbsent(brief);
	});

	it("renders detached worktrees cleanly", () => {
		const brief = buildWorkstreamLaunchBrief(
			makeInput({
				worktree: {
					label: "bt/detached",
					path: "/worktrees/org/repo/bt/detached",
					branch: null,
				},
			}),
		);

		assert.match(brief, /Branch: detached/);
		assertForbiddenPhrasesAbsent(brief);
	});
});
