import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { assistantStop, context, setup, verdict } from "./guard-harness.ts";

describe("continuation guard volatile state across the judge call", () => {
	// Pi resumes on any queued message without checking for an abort, so a nudge sent
	// after the user pressed ESC would restart the run they just cancelled.
	it("does not nudge when the run was aborted while the judge ran", async () => {
		const controller = new AbortController();
		const { pi } = setup({
			judge: async () => {
				controller.abort();
				return verdict;
			},
		});
		const { ctx } = context({ signal: controller.signal });

		await pi.fire("agent_end", assistantStop, ctx);

		assert.deepEqual(pi.sent, []);
		assert.equal(pi.entries.at(-1)?.block, "aborted");
	});

	it("does not nudge when the user queues input while the judge runs", async () => {
		const { pi, judged } = setup();
		const { ctx } = context({ pendingAfterJudge: true });

		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(judged.length, 1, "the precondition passed on the pre-await sample");
		assert.deepEqual(pi.sent, [], "the user's message wins over the stale decision");
		assert.equal(pi.entries.at(-1)?.block, "pending_user_messages");
	});

	it("bounds the judge call with a deadline combined with the run signal", async () => {
		let received: AbortSignal | undefined;
		const controller = new AbortController();
		const { pi } = setup({
			judge: async (args) => {
				received = args.signal;
				return verdict;
			},
		});
		const { ctx } = context({ signal: controller.signal });

		await pi.fire("agent_end", assistantStop, ctx);

		assert.ok(received, "the judge must receive a signal");
		assert.equal(received?.aborted, false);
		controller.abort();
		assert.equal(received?.aborted, true, "aborting the run aborts the judge call");
	});

	it("records a delivered nudge even when the notification throws", async () => {
		const { pi } = setup();
		const { ctx } = context({
			notify: () => {
				throw new Error("tui gone");
			},
		});

		await pi.fire("agent_end", assistantStop, ctx);

		assert.equal(pi.sent.length, 1);
		assert.equal(pi.entries.at(-1)?.outcome, "nudged");
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
