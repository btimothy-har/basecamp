import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadSkillsFromDir } from "@earendil-works/pi-coding-agent";
import registerPullRequest, { pullRequestSkillPath } from "../index.ts";

interface ResourceContribution {
	skillPaths: string[];
}
type ResourceHandler = () => ResourceContribution;

function createMockPi(): { pi: ExtensionAPI; resourceHandlers: ResourceHandler[] } {
	const resourceHandlers: ResourceHandler[] = [];
	const pi = {
		on(event: string, handler: ResourceHandler) {
			if (event === "resources_discover") resourceHandlers.push(handler);
		},
	};
	return { pi: pi as unknown as ExtensionAPI, resourceHandlers };
}

function preserveDepth(t: TestContext): void {
	const original = process.env.BASECAMP_AGENT_DEPTH;
	t.after(() => {
		if (original === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = original;
	});
}

describe("pull-request registration", () => {
	it("exposes the skill to primary sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const { pi, resourceHandlers } = createMockPi();

		registerPullRequest(pi);

		assert.equal(resourceHandlers.length, 1);
		assert.deepEqual(resourceHandlers[0]?.(), { skillPaths: [pullRequestSkillPath] });
	});

	it("hides the skill in subagent sessions", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const { pi, resourceHandlers } = createMockPi();

		registerPullRequest(pi);

		assert.equal(resourceHandlers.length, 0);
	});
});

describe("pull-request skill", () => {
	it("loads cleanly and owns the complete draft-first lifecycle", () => {
		const result = loadSkillsFromDir({ dir: path.dirname(pullRequestSkillPath), source: "pull-request-test" });
		const skill = result.skills[0];
		const content = fs.readFileSync(pullRequestSkillPath, "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(skill?.name, "pull-request");
		assert.match(skill?.description ?? "", /create|open|prepare/i);
		assert.doesNotMatch(content, /disable-model-invocation:\s*true/);

		for (const contract of [
			"stops before GitHub mutation",
			"active execution worktree",
			"Do not rebase",
			"always create it as a draft",
			"gh pr checks --watch --fail-fast",
			"If no interactive UI is available to answer",
			"never run `gh pr ready`",
			"Treat only an explicit affirmative answer as ready intent",
			"not a guaranteed hard gate",
			"Never merge, close, or approve",
		]) {
			assert.ok(content.includes(contract), `skill should state: ${contract}`);
		}
	});
});
