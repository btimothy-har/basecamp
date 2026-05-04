import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionEntry, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import {
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../../state/index.ts";
import { registerTitle, type TitleCompletion } from "../ui/title.ts";

async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-title-session-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

function messageEntry(message: unknown): SessionEntry {
	return { type: "message", message } as unknown as SessionEntry;
}

interface TestContextOptions {
	sessionId: string;
	branch?: SessionEntry[];
	onTitle?: (title: string) => void;
	onWidget?: (widget: unknown) => void;
	onNotify?: (message: string, level?: string) => void;
}

function createContext({
	sessionId,
	branch = [],
	onTitle = () => {},
	onWidget = () => {},
	onNotify = () => {},
}: TestContextOptions): ExtensionContext {
	return {
		hasUI: true,
		ui: {
			setTitle: onTitle,
			setWidget: (_id: string, widget: unknown) => onWidget(widget),
			notify: onNotify,
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
			getBranch: () => branch,
		},
	} as unknown as ExtensionContext;
}

function createPi() {
	const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => Promise<void> | void>();
	const commands = new Map<string, { handler: (args: string[], ctx: ExtensionContext) => Promise<void> }>();
	const sessionNames: string[] = [];
	const pi = {
		on: (event: string, handler: (event: unknown, ctx: ExtensionContext) => Promise<void> | void) => {
			handlers.set(event, handler);
		},
		registerCommand: (name: string, command: { handler: (args: string[], ctx: ExtensionContext) => Promise<void> }) => {
			commands.set(name, command);
		},
		setSessionName: (name: string) => sessionNames.push(name),
	} as unknown as ExtensionAPI;

	return { pi, handlers, commands, sessionNames };
}

async function flushBackgroundTitle(): Promise<void> {
	await new Promise<void>((resolve) => setImmediate(resolve));
}

afterEach(() => {
	resetCurrentSessionState();
});

describe("title session state", () => {
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

	it("keeps null title after invalid background response and retries on a later eligible agent start", async (t) => {
		const dir = await createTempDir(t);
		const sessionId = "018f0000-0000-7000-8000-00000000abcd";
		const widgets: unknown[] = [];
		const titles: string[] = [];
		const branch = [messageEntry({ role: "user", content: "Add hardened title generation tests." })];
		const responses = ["null", "Focused Title Tests"];
		const titleCompletion: TitleCompletion = async () => responses.shift() ?? "Unexpected Title";
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
		await handlers.get("before_agent_start")?.({ prompt: "Please continue." }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, null);
		assert.deepEqual(sessionNames, []);
		assert.deepEqual(titles, []);
		assert.ok(widgets.length > 0);
		assert.equal(widgets.at(-1), undefined);

		await handlers.get("before_agent_start")?.({ prompt: "Try again with more context." }, ctx);
		await flushBackgroundTitle();

		assert.equal(getCurrentSessionState().title, "Focused Title Tests");
		assert.deepEqual(sessionNames, ["Focused Title Tests [abcd]"]);
		assert.deepEqual(titles, ["Focused Title Tests [abcd]"]);
		assert.ok(widgets.length > 0);
		assert.notEqual(widgets.at(-1), undefined);
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
		const titleCompletion: TitleCompletion = async () => "this title has more than five words";
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
