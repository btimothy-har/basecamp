import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Context, Model } from "@earendil-works/pi-ai";
import { type GateDecision, runGate } from "../reviewer/gate.ts";
import { type ReviewAuditEntry, type ReviewDeps, reviewBashCommand } from "../reviewer/review.ts";

const fakeModel: Model<any> = {
	id: "claude-haiku",
	name: "Claude Haiku",
	api: "anthropic-messages",
	provider: "anthropic",
	baseUrl: "https://example.test",
	reasoning: false,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
	contextWindow: 200_000,
	maxTokens: 4096,
};

type FakeNotification = { message: string; type?: "info" | "warning" | "error" };

interface FakeReviewHarness {
	deps: ReviewDeps;
	auditEntries: ReviewAuditEntry[];
	confirmBodies: string[];
	notifications: FakeNotification[];
	confirmCalls: () => number;
	resolveModelCalls: () => number;
	runGateCalls: () => number;
}

function makeDecision(decision: GateDecision["decision"], reason = "Looks safe."): GateDecision {
	return { decision, risk: decision === "approve" ? "local" : "destructive", reason };
}

function makeDeps(
	overrides: Partial<{
		resolveModel: ReviewDeps["resolveModel"];
		runGate: ReviewDeps["runGate"];
		confirm: ReviewDeps["confirm"];
		hasUI: boolean;
		isSubagent: boolean;
	}> = {},
): FakeReviewHarness {
	const auditEntries: ReviewAuditEntry[] = [];
	const confirmBodies: string[] = [];
	const notifications: FakeNotification[] = [];
	let resolveModelCalls = 0;
	let runGateCalls = 0;
	let confirmCalls = 0;

	const deps: ReviewDeps = {
		resolveModel: async () => {
			resolveModelCalls += 1;
			if (overrides.resolveModel) return overrides.resolveModel();
			return { model: fakeModel, auth: { apiKey: "test-key" } };
		},
		recentMessages: () => ["Please make the requested repository change."],
		runGate: async (args) => {
			runGateCalls += 1;
			if (overrides.runGate) return overrides.runGate(args);
			return makeDecision("approve");
		},
		confirm: async (title, body) => {
			confirmCalls += 1;
			assert.ok(title === "Approve command?" || title === "Reviewer unavailable — approve command?");
			confirmBodies.push(body);
			if (overrides.confirm) return overrides.confirm(title, body);
			return true;
		},
		hasUI: overrides.hasUI ?? true,
		isSubagent: overrides.isSubagent ?? false,
		audit: (entry) => auditEntries.push(entry),
		notify: (message, type) => notifications.push({ message, type }),
	};

	return {
		deps,
		auditEntries,
		confirmBodies,
		notifications,
		confirmCalls: () => confirmCalls,
		resolveModelCalls: () => resolveModelCalls,
		runGateCalls: () => runGateCalls,
	};
}

async function assertAuditedNonAllow(
	command: string,
	deps: ReviewDeps,
	auditEntries: ReviewAuditEntry[],
): Promise<void> {
	await reviewBashCommand(command, deps);
	assert.ok(auditEntries.length > 0, `${command} should emit at least one audit entry`);
}

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

	it("blocks raw bq query commands during triage and audits the block", async () => {
		const harness = makeDeps();

		const outcome = await reviewBashCommand("bq query 'select 1'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /bq_query/);
		assert.equal(harness.resolveModelCalls(), 0);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.auditEntries.length, 1);
		assert.deepEqual(harness.auditEntries[0], {
			phase: "triage",
			action: "block",
			category: "bq-query",
			command: "bq query 'select 1'",
			reason:
				'Raw `bq query` execution through bash is blocked. Write the SQL to a .sql file and use bq_query({ path: "..." }) instead.',
		});
		assert.equal(harness.notifications.length, 1);
		assert.equal(harness.notifications[0]?.type, "warning");
		assert.match(harness.notifications[0]?.message ?? "", /reviewer blocked/);
		assert.match(harness.notifications[0]?.message ?? "", /bq_query/);
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

	it("escalates model-unavailable failures to the user and blocks declined commands", async () => {
		const harness = makeDeps({ resolveModel: async () => null, confirm: async () => false });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /reviewer unavailable/);
		assert.match(outcome?.reason ?? "", /user declined/);
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.category, "git-mutation");
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
		assert.equal(harness.auditEntries[0]?.category, "git-mutation");
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

	it("blocks route_to_user gh-mutation decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Publishing externally requires review."),
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

	it("blocks failClosed irreversible-remote decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("approve", "Force push matches the explicit request."),
			hasUI: false,
			isSubagent: true,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.equal(outcome?.block, true);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "subagent-collapse");
	});

	it("blocks route_to_user dangerous-shell decisions for subagents", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("route_to_user", "Recursive delete."),
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

	it("clamps failClosed approve decisions to user review and blocks declined commands", async () => {
		const harness = makeDeps({
			runGate: async () => makeDecision("approve", "Force push matches the explicit request."),
			confirm: async () => false,
		});

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.deepEqual(outcome, { block: true, reason: "User declined the command." });
		assert.equal(harness.confirmCalls(), 1);
		assert.equal(harness.auditEntries[0]?.action, "deny");
		assert.equal(harness.auditEntries[0]?.note, "route_to_user");
	});

	it("emits audit entries on every non-allow path", async () => {
		for (const command of [
			"bq query 'select 1'",
			"git commit -m 'test'",
			"git push --force",
			"gh pr create --title 'test'",
		]) {
			const harness = makeDeps({ runGate: async () => makeDecision("route_to_user", "Needs review.") });
			await assertAuditedNonAllow(command, harness.deps, harness.auditEntries);
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
