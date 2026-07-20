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
		const result = loadSkillsFromDir({ dir: path.dirname(codeReviewSkillPath), source: "code-review-test" });
		const content = fs.readFileSync(codeReviewSkillPath, "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(result.skills[0]?.name, "code-review");
		assert.match(result.skills[0]?.description ?? "", /review/i);
		assert.match(content, /disable-model-invocation:\s*true/);

		for (const token of ['skill({ name: "agents" })', "dispatch_agent", "wait_for_agent", "report_findings"]) {
			assert.equal(content.includes(token), true, `skill should reference ${token}`);
		}
		for (const agent of [
			"security-specialist",
			"testing-specialist",
			"docs-specialist",
			"code-clarity-specialist",
			"conventions-specialist",
			"general-reviewer",
		]) {
			assert.equal(content.includes(agent), true, `skill should dispatch ${agent}`);
		}
	});
});
