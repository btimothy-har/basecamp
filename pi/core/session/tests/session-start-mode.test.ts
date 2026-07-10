import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resetCopilotLaunchForTesting } from "../../agent-mode/copilot.ts";
import { getAgentMode, resetAgentMode } from "../../agent-mode/index.ts";
import { registerSession } from "../runtime/session.ts";
import {
	createDefaultSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../state/index.ts";

async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-session-start-mode-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

function createContext(sessionId: string, sessionFile: string | null = null): ExtensionContext {
	return {
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => sessionFile,
		},
	} as unknown as ExtensionContext;
}

type SessionStartHandler = () => Promise<void> | void;

class FakePi {
	readonly flags = new Map<string, { description: string; type: string }>();
	private readonly flagValues = new Map<string, unknown>();
	private sessionStart: SessionStartHandler | null = null;

	registerFlag(name: string, flag: { description: string; type: string }): void {
		this.flags.set(name, flag);
	}

	getFlag(name: string): unknown {
		return this.flagValues.get(name);
	}

	setFlag(name: string, value: unknown): void {
		this.flagValues.set(name, value);
	}

	on(event: string, handler: SessionStartHandler): void {
		if (event === "session_start") this.sessionStart = handler;
	}

	async emitSessionStart(): Promise<void> {
		assert.ok(this.sessionStart, "session_start handler should be registered");
		await this.sessionStart();
	}
}

afterEach(() => {
	resetCurrentSessionState();
	resetAgentMode();
	resetCopilotLaunchForTesting();
});

describe("registerSession copilot mode startup", () => {
	it("registers a boolean copilot flag", () => {
		const pi = new FakePi();

		registerSession(pi as unknown as ExtensionAPI);

		assert.equal(pi.flags.get("copilot")?.type, "boolean");
	});

	it("sets copilot mode on session_start when the copilot flag is present", async (t) => {
		const dir = await createTempDir(t);
		saveSessionState(
			{ ...createDefaultSessionState({ sessionId: "copilot-start", sessionFile: null }), agentMode: "supervisor" },
			dir,
		);
		initializeCurrentSessionState(createContext("copilot-start"), dir);
		const pi = new FakePi();
		registerSession(pi as unknown as ExtensionAPI);
		pi.setFlag("copilot", true);

		await pi.emitSessionStart();

		assert.equal(getAgentMode(), "copilot");
	});

	it("restores the stored mode on session_start when the copilot flag is absent", async (t) => {
		const dir = await createTempDir(t);
		saveSessionState(
			{ ...createDefaultSessionState({ sessionId: "restore-start", sessionFile: null }), agentMode: "supervisor" },
			dir,
		);
		initializeCurrentSessionState(createContext("restore-start"), dir);
		const pi = new FakePi();
		registerSession(pi as unknown as ExtensionAPI);

		await pi.emitSessionStart();

		assert.equal(getAgentMode(), "supervisor");
	});
});
