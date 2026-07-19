import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { SessionStartEvent } from "@earendil-works/pi-coding-agent";
import {
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../../session/state/index.ts";
import { registerTitle, type TitleCompletion } from "../title.ts";
import { createContext, createPi, createTempDir, flushBackgroundTitle, messageEntry } from "./title-state-harness.ts";

afterEach(() => {
	resetCurrentSessionState();
});

describe("title session state", () => {
	it("generates and applies a title on the first turn when no title exists", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		const widgets: unknown[] = [];
		const titles: string[] = [];
		const branch = [messageEntry({ role: "user", content: "Add hardened title generation tests." })];
		const titleCompletion: TitleCompletion = async () => "Focused Title Tests";
		const { pi, handlers, sessionNames } = createPi();
		const ctx = createContext({
			sessionId,
			branch,
			onTitle: (title) => titles.push(title),
			onWidget: (widget) => widgets.push(widget),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
		await handlers.get("turn_end")?.({ turnIndex: 0, message: "done", toolResults: [] }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, "Focused Title Tests");
		assert.deepEqual(sessionNames, ["Focused Title Tests [abcd]"]);
		assert.deepEqual(titles, ["Focused Title Tests [abcd]"]);
		assert.ok(widgets.length > 0);
		assert.notEqual(widgets.at(-1), undefined);
	});

	it("does not regenerate an existing title until the fifth cumulative turn", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		const branch = [messageEntry({ role: "user", content: "Add hardened title generation tests." })];
		const responses = ["Focused Title Tests", "Refreshed Title Tests"];
		let completionCalls = 0;
		const titleCompletion: TitleCompletion = async () => {
			completionCalls += 1;
			return responses.shift() ?? "Unexpected Title";
		};
		const { pi, handlers, sessionNames } = createPi();
		const ctx = createContext({ sessionId, branch });
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
		await handlers.get("turn_end")?.({ turnIndex: 0, message: "turn 1", toolResults: [] }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, "Focused Title Tests");
		assert.equal(completionCalls, 1);

		for (let index = 2; index <= 4; index += 1) {
			await handlers.get("turn_end")?.({ turnIndex: 0, message: `turn ${index}`, toolResults: [] }, ctx);
			await flushBackgroundTitle();
		}

		assert.equal(getCurrentSessionState().title, "Focused Title Tests");
		assert.equal(completionCalls, 1);

		await handlers.get("turn_end")?.({ turnIndex: 0, message: "turn 5", toolResults: [] }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, "Refreshed Title Tests");
		assert.equal(completionCalls, 2);
		assert.deepEqual(sessionNames, ["Focused Title Tests [abcd]", "Refreshed Title Tests [abcd]"]);
	});

	it("keeps the existing title when a fifth-turn refresh returns null", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		await saveSessionState(
			{ ...createDefaultSessionState({ sessionId, sessionFile: null }), title: "Existing Session Title" },
			dir,
		);

		const titles: string[] = [];
		const branch = [messageEntry({ role: "user", content: "Make the title refresh safer." })];
		let completionCalls = 0;
		const titleCompletion: TitleCompletion = async () => {
			completionCalls += 1;
			return "null";
		};
		const { pi, handlers, sessionNames } = createPi();
		const ctx = createContext({ sessionId, branch, onTitle: (title) => titles.push(title) });
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
		for (let index = 1; index <= 5; index += 1) {
			await handlers.get("turn_end")?.({ turnIndex: 0, message: `turn ${index}`, toolResults: [] }, ctx);
			await flushBackgroundTitle();
		}

		assert.equal(getCurrentSessionState().title, "Existing Session Title");
		assert.equal(completionCalls, 1);
		assert.deepEqual(sessionNames, []);
		assert.deepEqual(titles, ["Existing Session Title [abcd]"]);
	});

	it("clears the title state when the first-ever background completion returns null", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		const widgets: unknown[] = [];
		const titles: string[] = [];
		const branch = [messageEntry({ role: "user", content: "Add hardened title generation tests." })];
		const titleCompletion: TitleCompletion = async () => "null";
		const { pi, handlers, sessionNames } = createPi();
		const ctx = createContext({
			sessionId,
			branch,
			onTitle: (title) => titles.push(title),
			onWidget: (widget) => widgets.push(widget),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
		await handlers.get("turn_end")?.({ turnIndex: 0, message: "done", toolResults: [] }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, null);
		assert.deepEqual(sessionNames, []);
		assert.deepEqual(titles, []);
		assert.ok(widgets.length > 0);
		assert.equal(widgets.at(-1), undefined);
	});
});
