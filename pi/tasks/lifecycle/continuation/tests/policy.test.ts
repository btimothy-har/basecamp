import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createNudgeBudget, evaluatePreconditions, type NudgeBudget } from "#tasks/lifecycle/continuation/policy.ts";
import { MAX_CONSECUTIVE_NUDGES, type PolicyInput } from "#tasks/lifecycle/continuation/types.ts";

function input(overrides: Partial<PolicyInput> = {}): PolicyInput {
	return {
		providerErrored: false,
		planHandoffActive: false,
		pendingUserMessages: false,
		consecutiveNudges: 0,
		maxNudges: MAX_CONSECUTIVE_NUDGES,
		...overrides,
	};
}

describe("evaluatePreconditions", () => {
	it("blocks when the model call itself failed, leaving no agent judgment to nudge", () => {
		assert.deepEqual(evaluatePreconditions(input({ providerErrored: true })), {
			act: false,
			block: "provider_error",
		});
	});

	it("blocks plan_handoff_active when the plan tool owns the restart", () => {
		assert.deepEqual(evaluatePreconditions(input({ planHandoffActive: true })), {
			act: false,
			block: "plan_handoff_active",
		});
	});

	it("blocks pending_user_messages when the user has already spoken", () => {
		assert.deepEqual(evaluatePreconditions(input({ pendingUserMessages: true })), {
			act: false,
			block: "pending_user_messages",
		});
	});

	it("blocks cap_reached when consecutive nudges reach the bound", () => {
		assert.deepEqual(evaluatePreconditions(input({ consecutiveNudges: MAX_CONSECUTIVE_NUDGES })), {
			act: false,
			block: "cap_reached",
		});
	});

	it("reports provider_error when every condition holds simultaneously", () => {
		const allTrue = input({
			providerErrored: true,
			planHandoffActive: true,
			pendingUserMessages: true,
			consecutiveNudges: MAX_CONSECUTIVE_NUDGES,
		});
		assert.deepEqual(evaluatePreconditions(allTrue), { act: false, block: "provider_error" });
	});

	it("reports plan_handoff_active over the later conditions", () => {
		const overlapping = input({
			planHandoffActive: true,
			pendingUserMessages: true,
			consecutiveNudges: MAX_CONSECUTIVE_NUDGES,
		});
		assert.deepEqual(evaluatePreconditions(overlapping), {
			act: false,
			block: "plan_handoff_active",
		});
	});

	it("reports pending_user_messages over the cap", () => {
		const overlapping = input({
			pendingUserMessages: true,
			consecutiveNudges: MAX_CONSECUTIVE_NUDGES,
		});
		assert.deepEqual(evaluatePreconditions(overlapping), { act: false, block: "pending_user_messages" });
	});

	it("reports pending_user_messages over the cap", () => {
		const overlapping = input({
			pendingUserMessages: true,
			consecutiveNudges: MAX_CONSECUTIVE_NUDGES,
		});
		assert.deepEqual(evaluatePreconditions(overlapping), {
			act: false,
			block: "pending_user_messages",
		});
	});

	it("acts when every precondition is clear", () => {
		assert.deepEqual(evaluatePreconditions(input()), { act: true });
	});

	it("acts one below the cap, blocks at and above it", () => {
		assert.deepEqual(evaluatePreconditions(input({ consecutiveNudges: MAX_CONSECUTIVE_NUDGES - 1 })), {
			act: true,
		});
		assert.deepEqual(evaluatePreconditions(input({ consecutiveNudges: MAX_CONSECUTIVE_NUDGES })), {
			act: false,
			block: "cap_reached",
		});
		assert.deepEqual(evaluatePreconditions(input({ consecutiveNudges: MAX_CONSECUTIVE_NUDGES + 1 })), {
			act: false,
			block: "cap_reached",
		});
	});
});

describe("createNudgeBudget", () => {
	it("starts at zero", () => {
		assert.equal(createNudgeBudget().consecutive, 0);
	});

	it("increments on recordNudge", () => {
		const budget = createNudgeBudget();
		budget.recordNudge();
		assert.equal(budget.consecutive, 1);
	});

	it("accumulates multiple nudges", () => {
		const budget = createNudgeBudget();
		budget.recordNudge();
		budget.recordNudge();
		budget.recordNudge();
		assert.equal(budget.consecutive, 3);
	});

	it("zeroes on reset", () => {
		const budget = createNudgeBudget();
		budget.recordNudge();
		budget.recordNudge();
		budget.reset();
		assert.equal(budget.consecutive, 0);
	});

	it("accumulates again after a reset", () => {
		const budget = createNudgeBudget();
		budget.recordNudge();
		budget.reset();
		budget.recordNudge();
		assert.equal(budget.consecutive, 1);
	});
});

// Escalation history is intentionally not a precondition (see policy.ts): the
// module must never consult `escalate`, or a later legitimate stop in the same
// run would be wrongly suppressed.
describe("module surface", () => {
	it("exposes no escalate-flavored input or export", () => {
		const policyKeys: string[] = Object.keys(input());
		const budgetKeys: (keyof NudgeBudget)[] = ["consecutive", "recordNudge", "reset"];
		for (const key of [...policyKeys, ...budgetKeys]) {
			assert.ok(!key.toLowerCase().includes("escalate"), `unexpected escalate key: ${key}`);
		}
	});
});
