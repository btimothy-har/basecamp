import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadSkillsFromDir } from "@earendil-works/pi-coding-agent";
import registerCodeReview, { codeReviewSkillPath } from "../index.ts";

interface ResourceContribution {
	skillPaths: string[];
}
type ResourceHandler = () => ResourceContribution;

function createMockPi(): { pi: ExtensionAPI; toolNames: string[]; resourceHandlers: ResourceHandler[] } {
	const toolNames: string[] = [];
	const resourceHandlers: ResourceHandler[] = [];
	const pi = {
		registerTool(tool: { name: string }) {
			toolNames.push(tool.name);
		},
		on(event: string, handler: ResourceHandler) {
			if (event === "resources_discover") resourceHandlers.push(handler);
		},
	};
	return { pi: pi as unknown as ExtensionAPI, toolNames, resourceHandlers };
}

function preserveDepth(t: TestContext): void {
	const original = process.env.BASECAMP_AGENT_DEPTH;
	t.after(() => {
		if (original === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = original;
	});
}

describe("code-review registration", () => {
	it("registers report_findings and exposes the skill to primary sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const { pi, toolNames, resourceHandlers } = createMockPi();

		registerCodeReview(pi);

		assert.deepEqual(toolNames, ["report_findings"]);
		assert.equal(resourceHandlers.length, 1);
		assert.deepEqual(resourceHandlers[0]?.(), { skillPaths: [codeReviewSkillPath] });
	});

	it("registers the tool but hides the skill in subagent sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const { pi, toolNames, resourceHandlers } = createMockPi();

		registerCodeReview(pi);

		assert.deepEqual(toolNames, ["report_findings"]);
		assert.equal(resourceHandlers.length, 0);
	});
});

describe("code-review skill", () => {
	it("loads cleanly, stays model-hidden, and drives the reviewer dispatch flow", () => {
		const skillDir = path.dirname(codeReviewSkillPath);
		const result = loadSkillsFromDir({ dir: skillDir, source: "code-review-test" });
		const content = fs.readFileSync(codeReviewSkillPath, "utf8");
		const method = fs.readFileSync(path.join(skillDir, "references", "review-method.md"), "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(result.skills[0]?.name, "code-review");
		assert.match(result.skills[0]?.description ?? "", /review/i);
		assert.match(content, /disable-model-invocation:\s*true/);

		for (const token of [
			'skill({ name: "agents" })',
			"references/review-method.md",
			"dispatch_agent",
			"wait_for_agent",
			"report_findings",
			"adaptive general reviewers",
		]) {
			assert.equal(content.includes(token), true, `skill should reference ${token}`);
		}
		for (const probe of ["Establish contracts and invariants", "Test the test", "Validate rollout and recovery"]) {
			assert.equal(method.includes(probe), true, `review method should include ${probe}`);
		}
		for (const agent of [
			"security-specialist",
			"testing-specialist",
			"docs-specialist",
			"code-clarity-specialist",
			"conventions-specialist",
			"general-reviewer",
			"integration-specialist",
		]) {
			assert.equal(content.includes(agent), true, `skill should dispatch ${agent}`);
		}
	});

	it("shares trusted base guidance with the GitHub reviewer", () => {
		const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
		const workflow = fs.readFileSync(path.join(repoRoot, ".github", "workflows", "claude-review.yml"), "utf8");

		assert.match(workflow, /pull_request\.base\.sha/);
		assert.match(workflow, /basecamp-review-method\.md/);
		assert.match(workflow, /skills\/code-review\/references\/review-method\.md/);
		assert.doesNotMatch(workflow, /REVIEW\.md/);
		assert.equal(fs.existsSync(path.join(repoRoot, "REVIEW.md")), false);
	});
});
