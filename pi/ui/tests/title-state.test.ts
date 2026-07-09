import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { SessionStartEvent } from "@earendil-works/pi-coding-agent";
import {
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "#core/session/state/index.ts";
import { registerTitle, type TitleCompletion } from "../title.ts";
import { createContext, createPi, createTempDir, messageEntry } from "./title-state-harness.ts";

afterEach(() => {
	resetCurrentSessionState();
});

describe("title session state", () => {
	it("does not throw when core session state has not initialized yet", async () => {
		const { pi, handlers } = createPi();
		const ctx = createContext({ sessionId: "018f0000-0000-7000-8000-00000000abcd" });
		registerTitle(pi);

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
	});

	it("loads the startup title from current session state", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		await saveSessionState(
			{ ...createDefaultSessionState({ sessionId, sessionFile: null }), title: "Saved Session Title" },
			dir,
		);

		const titles: string[] = [];
		const { pi, handlers } = createPi();
		const ctx = createContext({ sessionId, onTitle: (title) => titles.push(title) });
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi);

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);

		assert.deepEqual(titles, ["Saved Session Title [abcd]"]);
	});

	it("clears existing title state and widget after invalid manual title without renaming the session", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		await saveSessionState(
			{ ...createDefaultSessionState({ sessionId, sessionFile: null }), title: "Existing Title" },
			dir,
		);

		const widgets: unknown[] = [];
		const titles: string[] = [];
		const notifications: Array<{ message: string; level?: string }> = [];
		const branch = [messageEntry({ role: "user", content: "Make the title safer." })];
		const titleCompletion: TitleCompletion = async () => "Fix";
		const { pi, handlers, commands, sessionNames } = createPi();
		const ctx = createContext({
			sessionId,
			branch,
			onTitle: (title) => titles.push(title),
			onWidget: (widget) => widgets.push(widget),
			onNotify: (message, level) => notifications.push({ message, level }),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });
		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);
		titles.length = 0;
		sessionNames.length = 0;

		await commands.get("title")?.handler([], ctx);

		assert.equal(getCurrentSessionState().title, null);
		assert.ok(widgets.length > 0);
		assert.equal(widgets.at(-1), undefined);
		assert.deepEqual(sessionNames, []);
		assert.deepEqual(titles, []);
		assert.ok(
			notifications.some(
				(notification) =>
					notification.level === "error" && /invalid title response from model/.test(notification.message),
			),
		);
	});

	it("applies a valid manual title from /title args without calling an LLM", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		const titleCompletion: TitleCompletion = async () => {
			throw new Error("titleCompletion should not be called for manual titles");
		};

		const titles: string[] = [];
		const widgets: unknown[] = [];
		const { pi, handlers, commands, sessionNames } = createPi();
		const ctx = createContext({
			sessionId,
			onTitle: (title) => titles.push(title),
			onWidget: (widget) => widgets.push(widget),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi, { titleCompletion });
		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);

		await commands.get("title")?.handler(["Refactor Auth Middleware"], ctx);

		assert.equal(getCurrentSessionState().title, "Refactor Auth Middleware");
		assert.deepEqual(sessionNames, ["Refactor Auth Middleware [abcd]"]);
		assert.deepEqual(titles, ["Refactor Auth Middleware [abcd]"]);
		assert.ok(widgets.length > 0);
		assert.notEqual(widgets.at(-1), undefined);
	});

	it("rejects an invalid manual title from /title args with a descriptive error", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		await saveSessionState(
			{ ...createDefaultSessionState({ sessionId, sessionFile: null }), title: "Existing Title" },
			dir,
		);

		const notifications: Array<{ message: string; level?: string }> = [];
		const { pi, handlers, commands, sessionNames } = createPi();
		const ctx = createContext({
			sessionId,
			onNotify: (message, level) => notifications.push({ message, level }),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi);
		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);

		await commands.get("title")?.handler(["Fix"], ctx);

		assert.ok(
			notifications.some(
				(notification) => notification.level === "error" && /Title needs at least 2 words/.test(notification.message),
			),
		);
		assert.equal(getCurrentSessionState().title, "Existing Title");
		assert.deepEqual(sessionNames, []);
	});

	it("normalizes a whitespace-only stored title to null on session start", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		await saveSessionState({ ...createDefaultSessionState({ sessionId, sessionFile: null }), title: "   \t " }, dir);

		const titles: string[] = [];
		const widgets: unknown[] = [];
		const { pi, handlers } = createPi();
		const ctx = createContext({
			sessionId,
			onTitle: (title) => titles.push(title),
			onWidget: (widget) => widgets.push(widget),
		});
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi);

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);

		assert.equal(getCurrentSessionState().title, null);
		assert.deepEqual(titles, []);
		assert.ok(widgets.length > 0);
		assert.equal(widgets.at(-1), undefined);
	});
});
