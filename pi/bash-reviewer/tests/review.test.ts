import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Context } from "@earendil-works/pi-ai";
import { runGate } from "#bash-reviewer/llm.ts";
import { reviewBashCommand } from "#bash-reviewer/review.ts";
import { makeDecision, makeDeps } from "./review-harness.ts";

describe("reviewBashCommand", () => {
	it("allows benign commands with zero model, gate, or audit overhead", async () => {
		const harness = makeDeps();

		const outcome = await reviewBashCommand("git status", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.resolveModelCalls(), 0);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.auditEntries.length, 0);
		assert.equal(harness.notifications.length, 0);
	});

	// The fast path is the reason a broken `fast` alias does not brick a headless session.
	it("allows fast-path commands even when no reviewer model can be resolved", async () => {
		const harness = makeDeps({
			hasUI: false,
			resolveModel: async () => null,
		});

		assert.equal(await reviewBashCommand("cat src/file.ts", harness.deps), undefined);
		assert.equal(harness.resolveModelCalls(), 0);
		assert.equal(harness.auditEntries.length, 0);
	});

	// The restrict-only invariant: an allowlisted executable buys nothing once a metacharacter
	// is present, because no static check here is trusted to understand what the shell will do.
	it("sends metacharacter-bearing commands to the gate despite an allowlisted executable", async () => {
		for (const command of ["cat f | sh", "git status && rm -rf build", "cat $(echo /etc/passwd)"]) {
			const harness = makeDeps({ runGate: async () => makeDecision("approve", "Reviewed.") });

			await reviewBashCommand(command, harness.deps);

			assert.equal(harness.runGateCalls(), 1, `${command} should reach the gate`);
		}
	});

	it("escalates model-unavailable failures to the user and allows confirmed commands", async () => {
		const harness = makeDeps({ resolveModel: async () => null, confirm: async () => true });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.resolveModelCalls(), 1);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.confirmCalls(), 1);
		assert.match(harness.confirmBodies[0] ?? "", /reviewer could not evaluate/);
		assert.match(harness.confirmBodies[0] ?? "", /reviewer model unavailable/);
		assert.match(harness.confirmBodies[0] ?? "", /git commit -m 'test'/);
		assert.equal(harness.notifications.length, 0);
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.category, undefined);
		assert.equal(harness.auditEntries[0]?.note, "escalated");
	});

	it("surfaces real runGate provider errors through failsafe", async () => {
		const providerError = "400 Reasoning is mandatory for this endpoint and cannot be disabled.";
		const harness = makeDeps({
			runGate: async (args) =>
				runGate({
					...args,
					complete: async () => {
						throw new Error(providerError);
					},
				}),
			confirm: async () => true,
		});

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.confirmCalls(), 1);
		assert.match(harness.confirmBodies[0] ?? "", /Reasoning is mandatory/);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.reason, providerError);
		assert.equal(harness.auditEntries[0]?.note, "escalated");
	});

	it("approves low-risk gate decisions without blocking", async () => {
		const harness = makeDeps({ runGate: async () => makeDecision("approve", "The commit is local and requested.") });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.runGateCalls(), 1);
		assert.equal(harness.confirmCalls(), 0);
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.risk, "local");
		assert.equal(harness.notifications.length, 1);
		assert.equal(harness.notifications[0]?.type, "info");
		assert.match(harness.notifications[0]?.message ?? "", /reviewer approved/);
		assert.match(harness.notifications[0]?.message ?? "", /local/);
		assert.match(harness.notifications[0]?.message ?? "", /The commit is local and requested\./);
	});

	it("routes to the user when UI is available and allows confirmed commands", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Publishing externally requires review."),
			confirm: async () => true,
		});

		const outcome = await reviewBashCommand("gh pr create --title 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.confirmCalls(), 1);
		assert.match(harness.confirmBodies[0] ?? "", /gh pr create/);
		assert.match(harness.confirmBodies[0] ?? "", /Publishing externally requires review/);
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
		assert.equal(harness.notifications.length, 0);
	});

	it("permits route_to_user git-mutation decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Ambiguous local change.", { category: "git-mutation" }),
			hasUI: false,
			isSubagent: true,
		});

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.confirmCalls(), 0);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.note, "subagent-collapse");
	});

	it("upgrades destructive-risk approvals to user review and allows confirmed commands", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("approve", "Force push matches the explicit request.", {
					risk: "destructive",
					category: "irreversible-remote",
				}),
			confirm: async () => true,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
	});

	it("threads worktreeDir into the gate context payload", async () => {
		const captured: Context[] = [];
		const harness = makeDeps({
			worktreeDir: "/home/user/.worktrees/repo/wt/branch",
			runGate: async (args) => {
				captured.push(args.context);
				return makeDecision("approve");
			},
		});

		await reviewBashCommand("sed -i s/x/y/ file.ts", harness.deps);

		assert.equal(harness.runGateCalls(), 1);
		const content = captured[0]?.messages[0]?.content;
		assert.equal(typeof content, "string");
		if (typeof content !== "string") throw new Error("expected string content");
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.equal(payload.worktree_dir, "/home/user/.worktrees/repo/wt/branch");
	});

	it("threads null worktree_dir when no worktree is active", async () => {
		const captured: Context[] = [];
		const harness = makeDeps({
			runGate: async (args) => {
				captured.push(args.context);
				return makeDecision("approve");
			},
		});

		await reviewBashCommand("git commit -m test", harness.deps);

		assert.equal(harness.runGateCalls(), 1);
		const content = captured[0]?.messages[0]?.content;
		assert.equal(typeof content, "string");
		if (typeof content !== "string") throw new Error("expected string content");
		const payload = JSON.parse(content.replace(/^Evaluate whether the bash command should run\. Input:\n\n/, ""));
		assert.equal(payload.worktree_dir, null);
	});
});
