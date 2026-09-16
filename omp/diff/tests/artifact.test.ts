import { describe, expect, test } from "bun:test";
import type { ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { buildDiffReviewArtifact, persistDiffReview } from "../artifact.ts";
import type { DiffSnapshot } from "../loader.ts";

const SNAPSHOT: DiffSnapshot = {
	repositoryRoot: "/worktree/basecamp",
	repository: "playground/basecamp",
	defaultBranch: "main",
	baseRevision: "base-sha",
	headRevision: "head-sha",
	patch: "diff --git a/a.ts b/a.ts\n+changed\n",
	files: [{ path: "a.ts", newRanges: [{ start: 1, end: 1 }], newLines: new Map([[1, "changed"]]) }],
};

function sessionManager(artifactsDir: string | null, artifactPath: string | null = "/artifacts/review.json") {
	const saved: { content: string; toolType: string }[] = [];
	const blobs: Buffer[] = [];
	const manager = {
		getArtifactsDir: () => artifactsDir,
		saveArtifact: async (content: string, toolType: string) => {
			saved.push({ content, toolType });
			return "review-42";
		},
		getArtifactPath: async () => artifactPath,
		putBlob: async (data: Buffer) => {
			blobs.push(data);
			return { displayPath: "/blobs/review.json" };
		},
	} as unknown as ExtensionContext["sessionManager"];
	return { manager, saved, blobs };
}

describe("diff review artifact", () => {
	test("captures the exact review scope, user notes, and agent projection outcome", () => {
		const artifact = buildDiffReviewArtifact(
			SNAPSHOT,
			"submitted",
			[{ filePath: "a.ts", oldRange: [2, 2], body: "removed behavior" }],
			["shown-id"],
			["stale-id"],
		);

		expect(artifact).toMatchObject({
			schema_version: 1,
			repository: "playground/basecamp",
			base_revision: "base-sha",
			head_revision: "head-sha",
			status: "submitted",
			user_annotations: [{ filePath: "a.ts", oldRange: [2, 2], body: "removed behavior" }],
			displayed_agent_annotation_ids: ["shown-id"],
			discarded_agent_annotation_ids: ["stale-id"],
		});
		expect(artifact.diff_sha256).toMatch(/^[0-9a-f]{64}$/);
	});

	test("persists through the session artifact store only when the id resolves", async () => {
		const harness = sessionManager("/artifacts");
		const artifact = buildDiffReviewArtifact(SNAPSHOT, "submitted", [], [], []);

		const persisted = await persistDiffReview(harness.manager, artifact);

		expect(persisted.reviewRef).toBe("artifact://review-42");
		expect(harness.saved[0]?.toolType).toBe("diff-review");
		expect(JSON.parse(harness.saved[0]!.content)).toEqual(artifact);
		expect(harness.blobs).toHaveLength(0);
	});

	test("falls back to a readable blob when the session has no artifact directory", async () => {
		const harness = sessionManager(null);
		const artifact = buildDiffReviewArtifact(SNAPSHOT, "cancelled", [], [], []);

		const persisted = await persistDiffReview(harness.manager, artifact);

		expect(persisted.reviewRef).toBe("/blobs/review.json");
		expect(harness.saved).toHaveLength(0);
		expect(JSON.parse(harness.blobs[0]!.toString())).toEqual(artifact);
	});

	test("fails closed when OMP returns an artifact id without a readable path", async () => {
		const harness = sessionManager("/artifacts", null);
		const artifact = buildDiffReviewArtifact(SNAPSHOT, "submitted", [], [], []);

		await expect(persistDiffReview(harness.manager, artifact)).rejects.toThrow(
			"OMP could not persist the diff review artifact",
		);
	});
});
