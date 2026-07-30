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
		assert.match(content, /"worktree_dir"/);
		assert.ok(content.includes(JSON.stringify(command)));
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.deepEqual(payload, { recent_human_messages: recentHumanMessages, command, worktree_dir: null });
	});

	it("includes the worktree directory when provided", () => {
		const context = buildGateContext([], "sed -i s/x/y/ file.ts", "/home/user/.worktrees/repo/wt/branch");
		const content = context.messages[0]?.content;
		if (typeof content !== "string") throw new Error("expected string content");
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.equal(payload.worktree_dir, "/home/user/.worktrees/repo/wt/branch");
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

	// R1 was relaxed from "lean deny" to "lean route_to_user" so reversible git operations
	// are not hard-denied based on intent second-guessing. File-edit carve-out is scoped
	// to worktree_dir non-null to avoid colliding with R5's protected-checkout caution.
	it("relaxes R1 to route_to_user and excludes normal git ops from deny", () => {
		assert.match(RULESET, /R1.*lean route_to_user/);
		assert.match(RULESET, /Do NOT deny normal git operations/);
		assert.match(RULESET, /push to a feature branch/);
		assert.match(RULESET, /worktree_dir is non-null.*not denied based on intent doubts/);
		assert.match(RULESET, /When worktree_dir is null, defer to R5/);
	});

	// The RULESET tells the model how to use the worktree_dir field to apply R5 correctly.
	it("describes the worktree_dir input field for R5 discrimination", () => {
		assert.match(RULESET, /worktree_dir/);
		assert.match(RULESET, /worktree_dir is null when the session is in the protected checkout/);
	});

	// R5 ties protected-checkout caution and worktree approval explicitly to worktree_dir,
	// avoiding self-contradiction from reusing "the working tree" term.
	it("clarifies R5 scope and approves local bash file edits in worktrees only", () => {
		assert.match(RULESET, /worktree_dir is null.*suspicious/);
		assert.match(RULESET, /worktree_dir is non-null.*approve with risk "local"/);
		assert.match(RULESET, /sed.*tee.*echo redirection.*perl -i/);
		assert.match(RULESET, /When worktree_dir is null, do NOT auto-approve/);
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
