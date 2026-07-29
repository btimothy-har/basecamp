import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildGateContext, GATE_TOOL, RULESET } from "#bash-reviewer/llm.ts";

describe("buildGateContext", () => {
	it("sets the ruleset, includes the gate tool, and embeds recent messages plus command as JSON", () => {
		const recentHumanMessages = ["Check the repo status.", "Now make a commit."];
		const command = "git commit -m 'test'";
		const context = buildGateContext(recentHumanMessages, command);

		assert.equal(context.systemPrompt, RULESET);
		assert.deepEqual(context.tools, [GATE_TOOL]);
		assert.equal(context.messages.length, 1);
		const message = context.messages[0];
		assert.equal(message?.role, "user");
		const content = message?.content;
		assert.equal(typeof content, "string");
		if (typeof content !== "string") throw new Error("expected string content");
		assert.match(content, /"recent_human_messages"/);
		assert.match(content, /"command"/);
		assert.ok(content.includes(JSON.stringify(command)));
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.deepEqual(payload, { recent_human_messages: recentHumanMessages, command });
	});
});

describe("RULESET", () => {
	// These were deterministic pre-LLM blocks before the command parser was deleted. The ruleset is
	// now the only place they are enforced, so dropping one would otherwise be a silent regression.
	it("carries the policies that used to be enforced without a model", () => {
		assert.match(RULESET, /bq query/);
		assert.match(RULESET, /bq_query/);
		assert.match(RULESET, /git worktree/);
		assert.match(RULESET, /recursive filesystem search/);
	});

	it("defines every category the reviewer keys policy on", () => {
		for (const category of [
			"git-mutation",
			"gh-publish",
			"irreversible-remote",
			"destructive-local",
			"bq-query",
			"wide-search",
			"other",
		]) {
			assert.ok(RULESET.includes(category), `ruleset should define the ${category} category`);
		}
	});

	// review.ts upgrades a destructive-risk approval to route_to_user, which only discriminates if
	// the model is told what separates a destructive command from a merely local one.
	it("defines the risk levels the destructive-approval upgrade depends on", () => {
		for (const risk of ['"none"', '"local"', '"destructive"']) {
			assert.ok(RULESET.includes(risk), `ruleset should define the ${risk} risk level`);
		}
	});
});
