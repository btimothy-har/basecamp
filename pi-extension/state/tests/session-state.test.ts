import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
	type BasecampSessionState,
	buildSessionStatePath,
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	loadSessionState,
	resetCurrentSessionState,
	saveSessionState,
	updateCurrentSessionState,
} from "../src/index.ts";

async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-session-state-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

async function writeStateFile(stateDir: string, sessionId: string, content: unknown): Promise<void> {
	const filePath = buildSessionStatePath(sessionId, stateDir);
	await fs.mkdir(path.dirname(filePath), { recursive: true });
	const text = typeof content === "string" ? content : JSON.stringify(content);
	await fs.writeFile(filePath, text ?? "null", "utf8");
}

function createContext(sessionId: string, sessionFile?: string): ExtensionContext {
	return {
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => sessionFile,
		},
	} as unknown as ExtensionContext;
}

describe("session state file helpers", () => {
	it("builds a state path from a session id and optional state dir", async (t) => {
		const dir = await createTempDir(t);

		assert.equal(buildSessionStatePath("abc123", dir), path.join(dir, "abc123.json"));
		assert.equal(buildSessionStatePath("../bad/id", dir), path.join(dir, "___bad_id.json"));
	});

	it("creates default state with nullable future fields", () => {
		const state = createDefaultSessionState({ sessionId: "s1", sessionFile: undefined });

		assert.equal(state.version, 1);
		assert.equal(state.sessionId, "s1");
		assert.equal(state.sessionFile, null);
		assert.equal(state.activeWorktree, null);
		assert.equal(state.agentMode, null);
		assert.equal(state.title, null);
		assert.match(state.updatedAt, /^\d{4}-\d{2}-\d{2}T/);
	});

	it("returns defaults when the state file is missing", async (t) => {
		const dir = await createTempDir(t);

		const state = loadSessionState({ sessionId: "missing", sessionFile: "/tmp/session.json" }, dir);

		assert.equal(state.version, 1);
		assert.equal(state.sessionId, "missing");
		assert.equal(state.sessionFile, "/tmp/session.json");
		assert.equal(state.title, null);
	});

	it("returns defaults for invalid JSON and wrong shapes", async (t) => {
		const dir = await createTempDir(t);
		await writeStateFile(dir, "invalid", "{ invalid json");
		await writeStateFile(dir, "wrong-shape", { version: 1, sessionId: "wrong-shape" });

		const invalid = loadSessionState({ sessionId: "invalid", sessionFile: null }, dir);
		const wrongShape = loadSessionState({ sessionId: "wrong-shape", sessionFile: null }, dir);

		assert.equal(invalid.sessionId, "invalid");
		assert.equal(invalid.title, null);
		assert.equal(wrongShape.sessionId, "wrong-shape");
		assert.equal(wrongShape.agentMode, null);
	});

	it("saves atomically with a fresh updatedAt and loads valid state", async (t) => {
		const dir = await createTempDir(t);
		const initial: BasecampSessionState = {
			version: 1,
			sessionId: "valid",
			sessionFile: "/tmp/session.json",
			updatedAt: "old",
			activeWorktree: {
				kind: "git-worktree",
				label: "feature",
				path: "/tmp/worktree",
				branch: "feature",
				created: false,
			},
			agentMode: "supervisor",
			title: "Saved title",
		};

		const saved = saveSessionState(initial, dir);
		const loaded = loadSessionState({ sessionId: "valid", sessionFile: "/tmp/session.json" }, dir);
		const tmpExists = await fs
			.access(`${buildSessionStatePath("valid", dir)}.tmp`)
			.then(() => true)
			.catch(() => false);

		assert.notEqual(saved.updatedAt, "old");
		assert.deepEqual(loaded, saved);
		assert.equal(tmpExists, false);
	});

	it("returns defaults for mismatched session id or session file", async (t) => {
		const dir = await createTempDir(t);
		const base = createDefaultSessionState({ sessionId: "expected", sessionFile: "/tmp/session.json" });
		await writeStateFile(dir, "expected", { ...base, sessionId: "other", title: "wrong id" });
		await writeStateFile(dir, "file-mismatch", {
			...base,
			sessionId: "file-mismatch",
			sessionFile: "/tmp/other-session.json",
			title: "wrong file",
		});

		const idMismatch = loadSessionState({ sessionId: "expected", sessionFile: "/tmp/session.json" }, dir);
		const fileMismatch = loadSessionState({ sessionId: "file-mismatch", sessionFile: "/tmp/session.json" }, dir);

		assert.equal(idMismatch.title, null);
		assert.equal(idMismatch.sessionId, "expected");
		assert.equal(fileMismatch.title, null);
		assert.equal(fileMismatch.sessionFile, "/tmp/session.json");
	});
});

describe("current session state", () => {
	it("initializes from context, updates with a patch, and persists", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});

		const initialized = initializeCurrentSessionState(createContext("current", "/tmp/current.json"), dir);
		const updated = updateCurrentSessionState({ title: "Current title", agentMode: "planning" });
		const loaded = loadSessionState({ sessionId: "current", sessionFile: "/tmp/current.json" }, dir);

		assert.equal(initialized.title, null);
		assert.equal(getCurrentSessionState().title, "Current title");
		assert.equal(updated.agentMode, "planning");
		assert.deepEqual(loaded, updated);
	});

	it("updates with an updater function", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});

		initializeCurrentSessionState(createContext("updater"), dir);
		const updated = updateCurrentSessionState((state) => ({ title: `${state.sessionId} title` }));

		assert.equal(updated.sessionFile, null);
		assert.equal(updated.title, "updater title");
	});
});
