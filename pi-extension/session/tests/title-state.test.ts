import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import {
	createDefaultSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../../state/src/index.ts";
import { registerTitle } from "../src/ui/title.ts";

async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-title-session-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

function createContext(sessionId: string, onTitle: (title: string) => void): ExtensionContext {
	return {
		hasUI: true,
		ui: {
			setTitle: onTitle,
			setWidget: () => {},
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
		},
	} as unknown as ExtensionContext;
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
		const handlers = new Map<string, (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>>();
		const pi = {
			on: (event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) => {
				handlers.set(event, handler);
			},
			registerCommand: () => {},
			setSessionName: () => {},
		} as unknown as ExtensionAPI;
		const ctx = createContext(sessionId, (title) => titles.push(title));
		initializeCurrentSessionState(ctx, dir);
		registerTitle(pi);

		await handlers.get("session_start")?.({ reason: "new" } as SessionStartEvent, ctx);

		assert.deepEqual(titles, ["Saved Session Title [abcd]"]);
	});
});
