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

	// R7 was narrowed from "All git worktree subcommands" to only mutating ones; the scope
	// clarification prevents the model from over-applying it to commands inside a worktree.
	it("narrows R7 to mutating worktree subcommands and scopes it to git worktree only", () => {
		assert.match(RULESET, /git worktree list.*read-only.*approved/);
		assert.match(RULESET, /does NOT apply to other commands/);
		assert.doesNotMatch(RULESET, /All .*git worktree.* subcommands.*must be denied/);
	});

	// R1 was relaxed from "lean deny" to "lean route_to_user" so reversible local operations
	// are not hard-denied based on intent second-guessing.
	it("relaxes R1 to route_to_user and excludes local git ops from deny", () => {
		assert.match(RULESET, /R1.*lean route_to_user/);
		assert.match(RULESET, /Do NOT deny normal local git operations/);
	});

	// R5 now clarifies the protected-checkout vs active-worktree distinction and explicitly
	// approves local bash file edits (sed, tee, etc.) in the worktree.
	it("clarifies R5 scope and approves local bash file edits in worktrees", () => {
		assert.match(RULESET, /does NOT apply to commands running inside an active worktree/);
		assert.match(RULESET, /sed.*tee.*echo redirection.*perl -i/);
		assert.match(RULESET, /approve with risk "local"/);
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
