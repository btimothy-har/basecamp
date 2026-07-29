import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Context, Model } from "@earendil-works/pi-ai";
import { reviewBashCommand } from "#bash-reviewer/review.ts";
import { assertAuditedGated, makeDecision, makeDeps } from "./review-harness.ts";

describe("reviewBashCommand", () => {
	// bq and wide-search were deterministic pre-LLM blocks; they are gate deny rules now, so the
	// observable contract is that the command reaches the gate and the verdict is plumbed through.
	it("sends bq query commands to the gate rather than blocking them statically", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("deny", 'Write the SQL to a .sql file and use bq_query({ path: "..." }).', {
					category: "bq-query",
				}),
		});

		const outcome = await reviewBashCommand("bq query 'select 1'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /bq_query/);
		assert.equal(harness.resolveModelCalls(), 1);
		assert.equal(harness.runGateCalls(), 1);
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.category, "bq-query");
		assert.equal(harness.notifications.length, 1);
		assert.equal(harness.notifications[0]?.type, "warning");
		assert.match(harness.notifications[0]?.message ?? "", /reviewer blocked/);
	});

	it("sends wide-ranging searches to the gate rather than blocking them statically", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("deny", "Scope the search to the project directory.", { category: "wide-search" }),
		});

		const outcome = await reviewBashCommand("grep -r foo /", harness.deps);

		assert.equal(outcome?.block, true);
		assert.equal(harness.runGateCalls(), 1);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.category, "wide-search");
	});

	it("escalates model-unavailable failures to the user and blocks declined commands", async () => {
		const harness = makeDeps({ resolveModel: async () => null, confirm: async () => false });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /reviewer unavailable/);
		assert.match(outcome?.reason ?? "", /user declined/);
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.category, undefined);
		assert.equal(harness.auditEntries[0]?.note, "escalated");
	});

	it("blocks gate failures without an interactive UI", async () => {
		const harness = makeDeps({ resolveModel: async () => null, hasUI: false });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /Reviewer unavailable/);
		assert.match(outcome?.reason ?? "", /no interactive UI/);
		assert.equal(harness.confirmCalls(), 0);
		assert.equal(harness.resolveModelCalls(), 1);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.category, undefined);
		assert.equal(harness.auditEntries[0]?.note, "no-ui");
	});

	it("escalates runGate null failures with UI and blocks them without UI", async () => {
		const withUI = makeDeps({ runGate: async () => null, confirm: async () => true });
		const withUIOutcome = await reviewBashCommand("git commit -m 'test'", withUI.deps);

		assert.equal(withUIOutcome, undefined);
		assert.equal(withUI.resolveModelCalls(), 1);
		assert.equal(withUI.runGateCalls(), 1);
		assert.equal(withUI.confirmCalls(), 1);
		assert.equal(withUI.auditEntries[0]?.phase, "failsafe");
		assert.equal(withUI.auditEntries[0]?.action, "approve");
		assert.equal(withUI.auditEntries[0]?.reason, "reviewer returned no decision");
		assert.match(withUI.confirmBodies[0] ?? "", /reviewer returned no decision/);
		assert.equal(withUI.auditEntries[0]?.note, "escalated");

		const noUI = makeDeps({ runGate: async () => null, hasUI: false });
		const noUIOutcome = await reviewBashCommand("git commit -m 'test'", noUI.deps);

		assert.equal(noUIOutcome?.block, true);
		assert.match(noUIOutcome?.reason ?? "", /Reviewer unavailable/);
		assert.match(noUIOutcome?.reason ?? "", /reviewer returned no decision/);
		assert.match(noUIOutcome?.reason ?? "", /no interactive UI/);
		assert.equal(noUI.confirmCalls(), 0);
		assert.equal(noUI.resolveModelCalls(), 1);
		assert.equal(noUI.runGateCalls(), 1);
		assert.equal(noUI.auditEntries[0]?.phase, "failsafe");
		assert.equal(noUI.auditEntries[0]?.action, "deny");
		assert.equal(noUI.auditEntries[0]?.reason, "reviewer returned no decision");
		assert.equal(noUI.auditEntries[0]?.note, "no-ui");
	});

	it("blocks denied gate decisions with the reviewer reason", async () => {
		const harness = makeDeps({ runGate: async () => makeDecision("deny", "This would publish a secret.") });

		const outcome = await reviewBashCommand("gh pr comment 123 --body github_pat_secret", harness.deps);

		assert.deepEqual(outcome, { block: true, reason: "This would publish a secret." });
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.notifications.length, 1);
		assert.equal(harness.notifications[0]?.type, "warning");
		assert.match(harness.notifications[0]?.message ?? "", /reviewer blocked/);
		assert.match(harness.notifications[0]?.message ?? "", /This would publish a secret\./);
	});

	it("routes to the user when UI is available and blocks declined commands", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Publishing externally requires review."),
			confirm: async () => false,
		});

		const outcome = await reviewBashCommand("gh pr create --title 'test'", harness.deps);

		assert.deepEqual(outcome, { block: true, reason: "User declined the command." });
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
	});

	it("blocks route_to_user decisions without an interactive UI", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Publishing externally requires review."),
			hasUI: false,
		});

		const outcome = await reviewBashCommand("gh pr create --title 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /not available without an interactive UI/);
		assert.equal(harness.confirmCalls(), 0);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "no-ui");
	});

	it("blocks route_to_user gh-publish decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("route_to_user", "Publishing externally requires review.", { category: "gh-publish" }),
			hasUI: false,
			isSubagent: true,
		});

		const outcome = await reviewBashCommand("gh pr create --title 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /autonomous agent/);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "subagent-collapse");
		assert.equal(harness.confirmCalls(), 0);
	});

	it("blocks destructive-risk approvals of irreversible-remote commands for subagents", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("approve", "Force push matches the explicit request.", {
					risk: "destructive",
					category: "irreversible-remote",
				}),
			hasUI: false,
			isSubagent: true,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.equal(outcome?.block, true);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "subagent-collapse");
	});

	it("blocks route_to_user destructive-local decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Recursive delete.", { category: "destructive-local" }),
			hasUI: false,
			isSubagent: true,
		});

		const outcome = await reviewBashCommand("rm -rf build", harness.deps);

		assert.equal(outcome?.block, true);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "subagent-collapse");
	});

	it("fails closed on failsafe for subagents", async () => {
		const harness = makeDeps({ resolveModel: async () => null, hasUI: false, isSubagent: true });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /Reviewer unavailable/);
		assert.match(outcome?.reason ?? "", /no interactive UI/);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "no-ui");
	});

	it("upgrades destructive-risk approvals to user review and blocks declined commands", async () => {
		const harness = makeDeps({
			runGate: async () =>
				makeDecision("approve", "Force push matches the explicit request.", {
					risk: "destructive",
					category: "irreversible-remote",
				}),
			confirm: async () => false,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.deepEqual(outcome, { block: true, reason: "User declined the command." });
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
	});

	it("emits audit entries on every gated path", async () => {
		for (const command of [
			"bq query 'select 1'",
			"git commit -m 'test'",
			"git push --force",
			"gh pr create --title 'test'",
		]) {
			const harness = makeDeps({ runGate: async () => makeDecision("route_to_user", "Needs review.") });
			await assertAuditedGated(command, harness.deps, harness.auditEntries);
		}
	});

	it("escalates unexpected gate-path errors with UI and blocks them without UI", async () => {
		const withUI = makeDeps({
			confirm: async () => true,
			resolveModel: async () => {
				throw new Error("registry failed");
			},
		});
		assert.equal(await reviewBashCommand("git commit -m 'test'", withUI.deps), undefined);
		assert.equal(withUI.confirmCalls(), 1);
		assert.equal(withUI.auditEntries[0]?.phase, "failsafe");
		assert.equal(withUI.auditEntries[0]?.action, "approve");
		assert.equal(withUI.auditEntries[0]?.reason, "registry failed");
		assert.equal(withUI.auditEntries[0]?.note, "escalated");

		const noUI = makeDeps({
			hasUI: false,
			runGate: async (_args: { model: Model<any>; auth: { apiKey?: string }; context: Context }) => {
				throw new Error("provider failed");
			},
		});
		const outcome = await reviewBashCommand("git push --force", noUI.deps);
		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /Reviewer unavailable/);
		assert.match(outcome?.reason ?? "", /no interactive UI/);
		assert.equal(noUI.confirmCalls(), 0);
		assert.equal(noUI.auditEntries[0]?.phase, "failsafe");
		assert.equal(noUI.auditEntries[0]?.action, "deny");
		assert.equal(noUI.auditEntries[0]?.reason, "provider failed");
		assert.equal(noUI.auditEntries[0]?.note, "no-ui");
	});
});
