import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
	buildSessionStatePath,
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	loadSessionState,
	resetCurrentSessionState,
	saveSessionState,
	updateCurrentSessionState,
} from "../../state/index.ts";
import {
	getAgentMode,
	onAgentModeChange,
	resetAgentMode,
	restoreAgentModeFromSessionState,
	setAgentMode,
} from "../agent-mode.ts";

async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-agent-mode-state-"));
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

afterEach(() => {
	resetCurrentSessionState();
	resetAgentMode();
});

describe("agent mode session state", () => {
	it("persists mode changes when session state is initialized", async (t) => {
		const dir = await createTempDir(t);
		initializeCurrentSessionState(createContext("persist-mode", "/tmp/persist-mode.json"), dir);

		const mode = setAgentMode("planning");
		const loaded = loadSessionState({ sessionId: "persist-mode", sessionFile: "/tmp/persist-mode.json" }, dir);

		assert.equal(mode, "planning");
		assert.equal(getAgentMode(), "planning");
		assert.equal(getCurrentSessionState().agentMode, "planning");
		assert.equal(loaded.agentMode, "planning");
	});

	it("persists an unchanged live mode when state has no mode yet", async (t) => {
		const dir = await createTempDir(t);
		initializeCurrentSessionState(createContext("persist-default"), dir);

		const mode = setAgentMode("executor");

		assert.equal(mode, "executor");
		assert.equal(getCurrentSessionState().agentMode, "executor");
	});

	it("restores mode from state without overwriting the state file", async (t) => {
		const dir = await createTempDir(t);
		saveSessionState(
			{ ...createDefaultSessionState({ sessionId: "restore-mode", sessionFile: null }), agentMode: "supervisor" },
			dir,
		);
		initializeCurrentSessionState(createContext("restore-mode"), dir);
		const seen: string[] = [];
		const unsubscribe = onAgentModeChange((mode) => seen.push(mode));

		const restored = restoreAgentModeFromSessionState();
		unsubscribe();
		const loaded = loadSessionState({ sessionId: "restore-mode", sessionFile: null }, dir);

		assert.equal(restored, "supervisor");
		assert.equal(getAgentMode(), "supervisor");
		assert.equal(loaded.agentMode, "supervisor");
		assert.deepEqual(seen, ["supervisor"]);
	});

	it("restores the default mode for null state without writing it", async (t) => {
		const dir = await createTempDir(t);
		initializeCurrentSessionState(createContext("restore-default"), dir);
		setAgentMode("analysis");
		updateCurrentSessionState({ agentMode: null });

		const restored = restoreAgentModeFromSessionState();
		const raw = await fs.readFile(buildSessionStatePath("restore-default", dir), "utf8");
		const loaded = JSON.parse(raw) as { agentMode: string | null };

		assert.equal(restored, "executor");
		assert.equal(getAgentMode(), "executor");
		assert.equal(loaded.agentMode, null);
	});
});
