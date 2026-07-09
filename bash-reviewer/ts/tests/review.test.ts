import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { runGate } from "../reviewer/gate.ts";
import { reviewBashCommand } from "../reviewer/review.ts";
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
		assert.equal(harness.auditEntries[0]?.category, "git-mutation");
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

	it("approves non-failClosed gate decisions without blocking", async () => {
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
			runGate: async () => makeDecision("route_to_user", "Ambiguous local change."),
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

	it("clamps failClosed approve decisions to user review and allows confirmed commands", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("approve", "Force push matches the explicit request."),
			confirm: async () => true,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.action, "approve");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
	});
});
