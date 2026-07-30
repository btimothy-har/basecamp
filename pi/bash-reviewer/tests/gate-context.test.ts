import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildGateContext, GATE_TOOL, RULESET } from "#bash-reviewer/llm.ts";

describe("buildGateContext", () => {
	it("sets the ruleset, includes the gate tool, and embeds recent messages plus command as JSON", () => {
		const recentHumanMessages = ["Check the repo status.", "Now make a commit."];
		const command = "git commit -m 'test'";
		const context = buildGateContext(recentHumanMessages, command, "/repo");

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
		assert.match(content, /"cwd"/);
		assert.ok(content.includes(JSON.stringify(command)));
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.deepEqual(payload, { recent_human_messages: recentHumanMessages, command, cwd: "/repo" });
	});

	it("embeds the cwd the command runs from", () => {
		const context = buildGateContext([], "sed -i s/x/y/ file.ts", "/home/user/.worktrees/repo/wt/branch");
		const content = context.messages[0]?.content;
		if (typeof content !== "string") throw new Error("expected string content");
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.equal(payload.cwd, "/home/user/.worktrees/repo/wt/branch");
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

	// Rules are grouped by outcome with a single precedence meta-rule; per-rule cross-references
	// ("defer to R5", "R2 already covers") are gone, so the precedence line is load-bearing.
	it("states the outcome precedence meta-rule", () => {
		assert.match(RULESET, /most restrictive outcome wins: deny over route_to_user over approve/);
	});

	// D2 denies only mutating worktree subcommands and is scoped to the git worktree subcommand
	// itself, so the model neither approves worktree management nor over-applies the rule to
	// commands that merely run inside a worktree directory.
	it("denies mutating worktree subcommands only, scoped to git worktree itself", () => {
		assert.match(RULESET, /git worktree list.*read-only.*approve/);
		assert.match(RULESET, /never other commands that merely run inside a worktree directory/);
		assert.doesNotMatch(RULESET, /All .*git worktree.* subcommands.*must be denied/);
	});

	// Normal git operations and contained file edits are approve rules, not intent judgments:
	// the branch exists to stop the gate from second-guessing reversible development work.
	it("approves normal git operations and contained file mutations", () => {
		assert.match(RULESET, /A1 Normal git operations.*approve with risk "local"/);
		assert.match(RULESET, /push to a feature branch/);
		assert.match(RULESET, /A2 Contained file mutations.*inside cwd or the system temp dir.*approve with risk "local"/);
	});

	// Containment is the single spatial concept: the cwd input field, the out-of-tree route
	// rule, and the risk definitions must all reference it.
	it("defines cwd containment for the out-of-tree rule and risk levels", () => {
		assert.match(RULESET, /cwd: the directory the command runs in; relative paths resolve here/);
		assert.match(RULESET, /U4 Out-of-tree writes.*outside cwd and outside the system temp dir/);
		assert.match(RULESET, /file writes outside cwd and the temp dir/);
	});

	// U5 keys on the command being unusual, not on tracing every command back to the
	// conversation; the routine-work sentence is what stops a fast model from routing a
	// git commit for feeling unrelated to the last message.
	it("scopes the unusual-command catch-all away from routine development", () => {
		assert.match(RULESET, /U5 Unusual active commands/);
		assert.match(RULESET, /never routed on this ground/);
		assert.doesNotMatch(RULESET, /Intent alignment/);
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
