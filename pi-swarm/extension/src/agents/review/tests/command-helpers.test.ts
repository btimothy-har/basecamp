import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import { isSubagent, persistReviewArtifact } from "../command-helpers.ts";
import type { Finding } from "../findings.ts";
import type { ReviewResult } from "../orchestrate.ts";

interface AnnotatedFinding extends Finding {
	reaction: string | null;
}

interface PersistedArtifact {
	scope: ReviewResult["scope"];
	verdict: ReviewResult["verdict"];
	findings: AnnotatedFinding[];
	createdAt: string;
}

const result: ReviewResult = {
	scope: {
		base: "origin/main",
		mergeBase: "abc1234",
		cwd: "/repo",
		label: "branch feature → origin/main",
	},
	verdict: {
		decision: "approve",
		blocking: false,
		counts: { critical: 0, high: 1, medium: 1, low: 0 },
	},
	findings: [
		{
			dimension: "security",
			severity: "high",
			file: "src/auth.ts",
			lineStart: 42,
			lineEnd: 44,
			title: "Token is logged",
			detail: "The access token is written to application logs.",
			remediation: "Remove the log statement and add a regression test.",
		},
		{
			dimension: "testing",
			severity: "medium",
			file: "src/auth.test.ts",
			lineStart: null,
			lineEnd: null,
			title: "Missing regression coverage",
			detail: "The changed auth flow has no regression coverage.",
			remediation: null,
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

function withScratch(t: TestContext): string {
	const originalScratch = process.env.BASECAMP_SCRATCH_DIR;
	t.after(() => restoreEnv("BASECAMP_SCRATCH_DIR", originalScratch));

	const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "code-review-scratch-"));
	process.env.BASECAMP_SCRATCH_DIR = scratch;
	return scratch;
}

function readArtifact(artifactPath: string): { json: string; artifact: PersistedArtifact } {
	const json = fs.readFileSync(artifactPath, "utf8");
	return { json, artifact: JSON.parse(json) as PersistedArtifact };
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
	it("writes a private prose-free artifact with aligned reactions under the scratch code-review directory", (t) => {
		const scratch = withScratch(t);

		const artifactPath = persistReviewArtifact(result, ["typed reaction", null]);
		const expectedDir = path.join(scratch, "code-review");
		const { json, artifact } = readArtifact(artifactPath);

		assert.equal(artifactPath.startsWith(`${expectedDir}${path.sep}`), true);
		assert.equal(fs.existsSync(artifactPath), true);
		assert.equal(fs.statSync(artifactPath).mode & 0o777, 0o600);
		assert.equal(fs.statSync(expectedDir).mode & 0o777, 0o700);
		assert.equal(artifact.findings[0]?.reaction, "typed reaction");
		assert.equal(artifact.findings[1]?.reaction, null);
		assert.equal(artifact.findings[0]?.dimension, "security");
		assert.equal(artifact.findings[0]?.severity, "high");
		assert.equal(artifact.findings[0]?.title, "Token is logged");
		assert.equal(artifact.findings[0]?.detail, "The access token is written to application logs.");
		assert.equal(artifact.findings[0]?.remediation, "Remove the log statement and add a regression test.");
		assert.equal(artifact.findings[1]?.dimension, "testing");
		assert.equal(artifact.findings[1]?.severity, "medium");
		assert.equal(artifact.findings[1]?.title, "Missing regression coverage");
		assert.equal("reviewers" in artifact, false);
		assert.equal(json.includes("prose"), false);
	});

	it("writes null reactions when reactions are omitted", (t) => {
		withScratch(t);

		const artifactPath = persistReviewArtifact(result, null);
		const { artifact } = readArtifact(artifactPath);

		assert.deepEqual(
			artifact.findings.map((finding) => finding.reaction),
			[null, null],
		);
	});
});
