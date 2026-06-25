import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Context, Model } from "@earendil-works/pi-ai";
import type { GateDecision } from "../reviewer/gate.ts";
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

interface FakeReviewHarness {
	deps: ReviewDeps;
	auditEntries: ReviewAuditEntry[];
	confirmBodies: string[];
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
	}> = {},
): FakeReviewHarness {
	const auditEntries: ReviewAuditEntry[] = [];
	const confirmBodies: string[] = [];
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
			assert.equal(title, "Approve command?");
			confirmBodies.push(body);
			if (overrides.confirm) return overrides.confirm(title, body);
			return true;
		},
		hasUI: overrides.hasUI ?? true,
		audit: (entry) => auditEntries.push(entry),
	};

	return {
		deps,
		auditEntries,
		confirmBodies,
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
	});

	it("fails open when the reviewer model is unavailable for fail-open commands", async () => {
		const harness = makeDeps({ resolveModel: async () => null });

		const outcome = await reviewBashCommand("git commit -m 'test'", harness.deps);

		assert.equal(outcome, undefined);
		assert.equal(harness.resolveModelCalls(), 1);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "allow");
		assert.equal(harness.auditEntries[0]?.category, "git-mutation");
	});

	it("fails closed when the reviewer model is unavailable for irreversible remote commands", async () => {
		const harness = makeDeps({ resolveModel: async () => null });

		const outcome = await reviewBashCommand("git push --force", harness.deps);

		assert.equal(outcome?.block, true);
		assert.match(outcome?.reason ?? "", /Reviewer unavailable/);
		assert.equal(harness.resolveModelCalls(), 1);
		assert.equal(harness.runGateCalls(), 0);
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "failsafe");
		assert.equal(harness.auditEntries[0]?.action, "block");
		assert.equal(harness.auditEntries[0]?.category, "irreversible-remote");
	});

	it("applies runGate null fail-safe behavior for fail-open and fail-closed commands", async () => {
		const failOpen = makeDeps({ runGate: async () => null });
		const failOpenOutcome = await reviewBashCommand("git commit -m 'test'", failOpen.deps);

		assert.equal(failOpenOutcome, undefined);
		assert.equal(failOpen.resolveModelCalls(), 1);
		assert.equal(failOpen.runGateCalls(), 1);
		assert.equal(failOpen.auditEntries[0]?.phase, "failsafe");
		assert.equal(failOpen.auditEntries[0]?.action, "allow");

		const failClosed = makeDeps({ runGate: async () => null });
		const failClosedOutcome = await reviewBashCommand("git push --force", failClosed.deps);

		assert.equal(failClosedOutcome?.block, true);
		assert.equal(failClosed.resolveModelCalls(), 1);
		assert.equal(failClosed.runGateCalls(), 1);
		assert.equal(failClosed.auditEntries[0]?.phase, "failsafe");
		assert.equal(failClosed.auditEntries[0]?.action, "block");
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
	});

	it("blocks denied gate decisions with the reviewer reason", async () => {
		const harness = makeDeps({ runGate: async () => makeDecision("deny", "This would publish a secret.") });

		const outcome = await reviewBashCommand("gh pr comment 123 --body github_pat_secret", harness.deps);

		assert.deepEqual(outcome, { block: true, reason: "This would publish a secret." });
		assert.equal(harness.auditEntries.length, 1);
		assert.equal(harness.auditEntries[0]?.phase, "gate");
		assert.equal(harness.auditEntries[0]?.action, "deny");
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

	it("fails safely instead of throwing on unexpected gate-path errors", async () => {
		const failOpen = makeDeps({
			resolveModel: async () => {
				throw new Error("registry failed");
			},
		});
		assert.equal(await reviewBashCommand("git commit -m 'test'", failOpen.deps), undefined);
		assert.equal(failOpen.auditEntries[0]?.phase, "failsafe");
		assert.equal(failOpen.auditEntries[0]?.action, "allow");

		const failClosed = makeDeps({
			runGate: async (_args: { model: Model<any>; auth: { apiKey?: string }; context: Context }) => {
				throw new Error("provider failed");
			},
		});
		const outcome = await reviewBashCommand("git push --force", failClosed.deps);
		assert.equal(outcome?.block, true);
		assert.equal(failClosed.auditEntries[0]?.phase, "failsafe");
		assert.equal(failClosed.auditEntries[0]?.action, "block");
	});
});
