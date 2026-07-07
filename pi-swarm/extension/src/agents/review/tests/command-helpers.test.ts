import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { isSubagent, persistReviewArtifact } from "../command-helpers.ts";
import type { ReviewResult } from "../orchestrate.ts";

const result: ReviewResult = {
	scope: {
		base: "main",
		head: "HEAD",
		cwd: "/repo",
		label: "branch feature → main",
	},
	verdict: {
		decision: "approve",
		blocking: false,
		counts: { critical: 0, high: 0, medium: 0, low: 0 },
	},
	findings: [],
	reviewers: [
		{
			agent: "general-reviewer",
			dimension: "general",
			status: "completed",
			prose: "raw reviewer prose must be preserved",
			error: null,
			findings: [],
			gap: null,
		},
	],
	createdAt: "2026-07-07T12:00:00.000Z",
};

function restoreEnv(name: string, value: string | undefined): void {
	if (value === undefined) {
		delete process.env[name];
		return;
	}
	process.env[name] = value;
}

describe("isSubagent", () => {
	it("returns false when BASECAMP_AGENT_DEPTH is unset or zero and true when greater than zero", (t) => {
		const original = process.env.BASECAMP_AGENT_DEPTH;
		t.after(() => restoreEnv("BASECAMP_AGENT_DEPTH", original));

		delete process.env.BASECAMP_AGENT_DEPTH;
		assert.equal(isSubagent(), false);

		process.env.BASECAMP_AGENT_DEPTH = "0";
		assert.equal(isSubagent(), false);

		process.env.BASECAMP_AGENT_DEPTH = "1";
		assert.equal(isSubagent(), true);
	});
});

describe("persistReviewArtifact", () => {
	it("writes a private artifact under the scratch code-review directory preserving raw prose", (t) => {
		const originalScratch = process.env.BASECAMP_SCRATCH_DIR;
		t.after(() => restoreEnv("BASECAMP_SCRATCH_DIR", originalScratch));

		const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "code-review-scratch-"));
		process.env.BASECAMP_SCRATCH_DIR = scratch;

		const artifactPath = persistReviewArtifact(result);
		const expectedDir = path.join(scratch, "code-review");

		assert.equal(artifactPath.startsWith(`${expectedDir}${path.sep}`), true);
		assert.equal(fs.existsSync(artifactPath), true);
		assert.equal(fs.statSync(artifactPath).mode & 0o777, 0o600);
		assert.equal(fs.statSync(expectedDir).mode & 0o777, 0o700);
		assert.deepEqual(JSON.parse(fs.readFileSync(artifactPath, "utf8")), result);
	});
});
