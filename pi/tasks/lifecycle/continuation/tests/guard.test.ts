import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
	CONTINUATION_NUDGE_TYPE,
	type ContinuationGuardDeps,
	registerContinuationGuard,
} from "#tasks/lifecycle/continuation/index.ts";
import type { ContinuationAuditEntry, ContinuationVerdict } from "#tasks/lifecycle/continuation/types.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";

type Handler = (event: any, ctx: ExtensionContext) => unknown;

interface SentMessage {
	customType: string;
	content: string;
	display: boolean;
	deliverAs: string;
}

class FakePi {
	readonly sent: SentMessage[] = [];
	readonly entries: ContinuationAuditEntry[] = [];
	readonly handlers = new Map<string, Handler[]>();
	readOnly = false;

	on(event: string, handler: Handler): void {
		const existing = this.handlers.get(event) ?? [];
		existing.push(handler);
		this.handlers.set(event, existing);
	}

	sendMessage(
		message: { customType: string; content: string; display: boolean },
		options: { deliverAs: string },
	): void {
		this.sent.push({ ...message, deliverAs: options.deliverAs });
	}

	appendEntry(_type: string, entry: ContinuationAuditEntry): void {
		this.entries.push(entry);
	}

	getFlag(name: string): unknown {
		return name === "read-only" ? this.readOnly : undefined;
	}

	async fire(event: string, payload: unknown, ctx: ExtensionContext): Promise<void> {
		for (const handler of this.handlers.get(event) ?? []) await handler(payload, ctx);
	}
}

function runtime(goal: string | null = "Ship the guard"): TasksRuntime {
	return {
		state: { goal, tasks: [{ label: "Implement", description: "d", criteria: "c", status: "active", review: null }] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget() {},
		persistState() {},
	} as unknown as TasksRuntime;
}

const assistantStop = {
	messages: [{ role: "assistant", content: [{ type: "text", text: "Let me check the wiring." }] }],
};

const verdict: ContinuationVerdict = { retrigger: true, category: "I", reason: "announced a next step it never took" };

function context(overrides: Partial<{ hasUI: boolean; pending: boolean; notify: (m: string) => void }> = {}) {
	const notifications: string[] = [];
	const ctx = {
		hasUI: overrides.hasUI ?? true,
		hasPendingMessages: () => overrides.pending ?? false,
		sessionManager: { getEntries: () => [] },
		ui: { notify: (message: string) => notifications.push(message) },
	} as unknown as ExtensionContext;
	return { ctx, notifications };
}

function setup(deps: Partial<ContinuationGuardDeps> = {}, tasks: TasksRuntime = runtime()) {
	const pi = new FakePi();
	const judged: unknown[] = [];
	registerContinuationGuard(pi as unknown as ExtensionAPI, tasks, {
		planHandoffActive: () => false,
		isSubagentRun: () => false,
		resolveModel: async () => ({ model: { id: "haiku" } as any, auth: { apiKey: "k" } }),
		judge: async (args) => {
			judged.push(args.context);
			return verdict;
		},
		...deps,
	});
	return { pi, judged };
}

describe("continuation guard nudging", () => {
	it("sends exactly one hidden followUp nudge on a retrigger verdict", async () => {
		const { pi } = setup();
		const { ctx, notifications } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(pi.sent.length, 1);
		assert.equal(pi.sent[0]?.customType, CONTINUATION_NUDGE_TYPE);
		assert.equal(pi.sent[0]?.display, false);
		assert.equal(pi.sent[0]?.deliverAs, "followUp");
		assert.match(pi.sent[0]?.content ?? "", /Continue the work where you left off/);
		assert.match(pi.sent[0]?.content ?? "", /announced a next step it never took/);
		assert.equal(notifications.length, 1);
		assert.deepEqual(pi.entries.at(-1), {
			outcome: "nudged",
			subagent: false,
			consecutiveNudges: 1,
			category: "I",
			reason: verdict.reason,
		});
	});

	it("addresses a dispatched agent's own judgment rather than the user", async () => {
		const { pi } = setup({ isSubagentRun: () => true });
		const { ctx, notifications } = context({ hasUI: false });

		await pi.fire("agent_end", assistantStop, ctx);

		assert.match(pi.sent[0]?.content ?? "", /no user will answer a question/);
		assert.doesNotMatch(pi.sent[0]?.content ?? "", /call escalate/);
		assert.equal(notifications.length, 0, "a subagent has no UI to notify");
		assert.equal(pi.entries.at(-1)?.subagent, true);
	});

	it("holds without nudging when the rubric vetoes the stop", async () => {
		const { pi } = setup({ judge: async () => ({ retrigger: false, category: "Q", reason: "asked the user" }) });
		const { ctx, notifications } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(notifications.length, 0);
		assert.equal(pi.entries.at(-1)?.outcome, "held");
		assert.equal(pi.entries.at(-1)?.category, "Q");
	});

	it("stops nudging once the cap is reached and resumes after a user message", async () => {
		const { pi } = setup();
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);
		await pi.fire("agent_end", assistantStop, ctx);
		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(pi.sent.length, 2, "cap bounds the chain at two nudges");
		assert.equal(pi.entries.at(-1)?.block, "cap_reached");

		await pi.fire("message_start", { message: { role: "user", content: "carry on" } }, ctx);
		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(pi.sent.length, 3, "a genuine user message resets the budget");
	});

	it("does not let its own nudge reset the budget", async () => {
		const { pi } = setup();
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);
		await pi.fire("message_start", { message: { role: "custom", customType: CONTINUATION_NUDGE_TYPE } }, ctx);
		await pi.fire("agent_end", assistantStop, ctx);
		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(pi.sent.length, 2);
	});
});

describe("continuation guard preconditions", () => {
	it("never consults the judge when the plan tool owns the restart", async () => {
		const { pi, judged } = setup({ planHandoffActive: () => true });
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(judged.length, 0, "a blocked precondition must not cost a model call");
		assert.equal(pi.entries.at(-1)?.block, "plan_handoff_active");
	});

	it("honors stop_work for the run that set it, then re-arms", async () => {
		const { pi } = setup();
		const { ctx } = context();

		await pi.fire("tool_result", { toolName: "complete_task", isError: false, details: { stop_work: true } }, ctx);
		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(pi.entries.at(-1)?.block, "stop_work");

		await pi.fire("agent_end", assistantStop, ctx);
		assert.equal(pi.sent.length, 1, "stop_work is scoped to the run that invoked it");
	});

	it("stands down when the user has already queued input", async () => {
		const { pi, judged } = setup();
		const { ctx } = context({ pending: true });

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(judged.length, 0);
		assert.equal(pi.entries.at(-1)?.block, "pending_user_messages");
	});

	it("stands down when the model call itself failed", async () => {
		const { pi, judged } = setup();
		const { ctx } = context();

		await pi.fire("agent_end", { messages: [{ role: "assistant", content: [], stopReason: "error" }] }, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(judged.length, 0);
		assert.equal(pi.entries.at(-1)?.block, "provider_error");
	});
});

describe("continuation guard fail-open behavior", () => {
	it("does not nudge when the fast model is unavailable", async () => {
		const { pi } = setup({ resolveModel: async () => null });
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(pi.entries.at(-1)?.outcome, "no_verdict");
		assert.match(pi.entries.at(-1)?.reason ?? "", /fast model unavailable/);
	});

	it("does not nudge when the judge returns no decision", async () => {
		const { pi } = setup({ judge: async () => null });
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.match(pi.entries.at(-1)?.reason ?? "", /no decision/);
	});

	it("does not nudge when the judge throws", async () => {
		const { pi } = setup({
			judge: async () => {
				throw new Error("provider exploded");
			},
		});
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.match(pi.entries.at(-1)?.reason ?? "", /provider exploded/);
	});

	it("skips the model call when the run produced no assistant text", async () => {
		const { pi, judged } = setup();
		const { ctx } = context();

		await pi.fire("agent_end", { messages: [{ role: "user", content: "hi" }] }, ctx);

		assert.equal(judged.length, 0);
		assert.match(pi.entries.at(-1)?.reason ?? "", /no assistant message/);
	});

	it("passes the goal, task snapshot, and subagent flag to the judge", async () => {
		const { pi, judged } = setup({ isSubagentRun: () => true });
		const { ctx } = context();

		await pi.fire("agent_end", assistantStop, ctx);

		const prompt = (judged[0] as { systemPrompt: string }).systemPrompt;
		const payload = (judged[0] as { messages: { content: string }[] }).messages[0]?.content ?? "";
		assert.ok(!prompt.includes("Q (Asked)"), "the subagent rubric withholds veto Q");
		assert.match(payload, /Ship the guard/);
		assert.match(payload, /"status": "active"/);
	});
});
