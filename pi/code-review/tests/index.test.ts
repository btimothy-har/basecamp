import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadSkillsFromDir, parseFrontmatter, stripFrontmatter } from "@earendil-works/pi-coding-agent";
import registerCodeReview, { codeReviewPromptPath, codeReviewSkillPath } from "#code-review/index.ts";

interface ResourceContribution {
	promptPaths: string[];
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
	it("registers the result tool and exposes the prompt and skill to primary sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const { pi, toolNames, resourceHandlers } = createMockPi();

		registerCodeReview(pi);

		assert.deepEqual(toolNames, ["report_findings"]);
		assert.equal(resourceHandlers.length, 1);
		assert.deepEqual(resourceHandlers[0]?.(), {
			promptPaths: [codeReviewPromptPath],
			skillPaths: [codeReviewSkillPath],
		});
	});

	it("registers no code-review surfaces in subagent sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const { pi, toolNames, resourceHandlers } = createMockPi();

		registerCodeReview(pi);

		assert.deepEqual(toolNames, []);
		assert.equal(resourceHandlers.length, 0);
	});
});

describe("code-review prompt", () => {
	it("loads the method skill and passes additional instructions without duplicating it", () => {
		const prompt = fs.readFileSync(codeReviewPromptPath, "utf8");
		const { frontmatter } = parseFrontmatter<Record<string, string>>(prompt);
		const body = stripFrontmatter(prompt);

		assert.equal(path.basename(codeReviewPromptPath), "code-review.md");
		assert.match(frontmatter.description ?? "", /independent multi-agent review/);
		assert.equal(frontmatter["argument-hint"], "[additional instructions]");
		assert.match(body, /skill\(\{ name: "code-review" \}\)/);
		assert.match(body, /apply\s+that guidance/);
		assert.match(body, /Additional instructions:/);
		assert.match(body, /\$\{ARGUMENTS:-None\.\}/);
		assert.doesNotMatch(body, /dispatch_agent|wait_for_agent|report_findings|security-specialist/);
	});
});

describe("code-review skill", () => {
	it("loads cleanly, stays model-invocable, and owns the reviewer dispatch flow", () => {
		const skillDir = path.dirname(codeReviewSkillPath);
		const result = loadSkillsFromDir({ dir: skillDir, source: "code-review-test" });
		const content = fs.readFileSync(codeReviewSkillPath, "utf8");
		const method = fs.readFileSync(path.join(skillDir, "references", "review-method.md"), "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(result.skills[0]?.name, "code-review");
		assert.match(result.skills[0]?.description ?? "", /guidance.*review/i);
		assert.match(result.skills[0]?.description ?? "", /explicit request.*casual requests/i);
		assert.doesNotMatch(content, /disable-model-invocation:\s*true/);
		assert.doesNotMatch(content, /\/(?:skill:)?code-review/);

		for (const token of [
			'skill({ name: "agents" })',
			'skill({ name: "code-review", reference: "references/review-method.md" })',
			"references/review-method.md",
			"dispatch_agent",
			"wait_for_agent",
			"report_findings",
			"adaptive general reviewers",
			"review chair",
			"Show the exact summary to the user",
			"report_findings({ scope, summary, findings })",
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
});
