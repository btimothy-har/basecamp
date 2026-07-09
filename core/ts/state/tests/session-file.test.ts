import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	type BasecampSessionState,
	buildSessionStatePath,
	createDefaultSessionState,
	initializeCurrentSessionStateForEvent,
	loadSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../index.ts";
import { createContext, createTempDir, writeStateFile, writeTranscriptHeader } from "./session-state-harness.ts";

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
		await writeStateFile(dir, "old-worktree-shape", {
			...createDefaultSessionState({ sessionId: "old-worktree-shape", sessionFile: null }),
			activeWorktree: {
				kind: "git-worktree",
				label: "feature",
				path: "/tmp/worktree",
				branch: "feature",
				created: false,
			},
		});

		const invalid = loadSessionState({ sessionId: "invalid", sessionFile: null }, dir);
		const wrongShape = loadSessionState({ sessionId: "wrong-shape", sessionFile: null }, dir);
		const oldWorktreeShape = loadSessionState({ sessionId: "old-worktree-shape", sessionFile: null }, dir);

		assert.equal(invalid.sessionId, "invalid");
		assert.equal(invalid.title, null);
		assert.equal(wrongShape.sessionId, "wrong-shape");
		assert.equal(wrongShape.agentMode, null);
		assert.equal(oldWorktreeShape.activeWorktree, null);
	});

	it("strips legacy fields when loading valid state", async (t) => {
		const dir = await createTempDir(t);
		await writeStateFile(dir, "legacy-fields", {
			...createDefaultSessionState({ sessionId: "legacy-fields", sessionFile: "/tmp/session.json" }),
			activePR: { number: 123 },
			activeIssueDraft: { title: "old draft" },
		});

		const loaded = loadSessionState({ sessionId: "legacy-fields", sessionFile: "/tmp/session.json" }, dir);

		assert.equal("activePR" in loaded, false);
		assert.equal("activeIssueDraft" in loaded, false);
		assert.deepEqual(Object.keys(loaded).sort(), [
			"activeWorktree",
			"agentMode",
			"sessionFile",
			"sessionId",
			"title",
			"updatedAt",
			"version",
		]);
	});

	it("saves atomically with a fresh updatedAt and loads valid state", async (t) => {
		const dir = await createTempDir(t);
		const initial: BasecampSessionState = {
			version: 1,
			sessionId: "valid",
			sessionFile: "/tmp/session.json",
			updatedAt: "old",
			activeWorktree: {
				version: 1,
				repoName: "repo",
				repoRoot: "/tmp/repo",
				remoteUrl: "git@github.com:test/repo.git",
				worktree: {
					kind: "git-worktree",
					label: "feature",
					path: "/tmp/worktree",
					branch: "feature",
					created: false,
				},
				updatedAt: "2026-05-03T00:00:00.000Z",
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

describe("fork session state", () => {
	it("copies selected parent state fields into the child state file", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});
		const parentSessionFile = path.join(dir, "parent.jsonl");
		const childSessionFile = path.join(dir, "child.jsonl");
		await writeTranscriptHeader(parentSessionFile, "parent");
		const parentState = saveSessionState(
			{
				...createDefaultSessionState({ sessionId: "parent", sessionFile: parentSessionFile }),
				activeWorktree: {
					version: 1,
					repoName: "repo",
					repoRoot: "/tmp/repo",
					remoteUrl: "git@github.com:test/repo.git",
					worktree: {
						kind: "git-worktree",
						label: "feature",
						path: "/tmp/worktree",
						branch: "feature",
						created: false,
					},
					updatedAt: "2026-05-03T00:00:00.000Z",
				},
				agentMode: "executor",
				title: "Parent title",
			},
			dir,
		);

		const childState = initializeCurrentSessionStateForEvent(
			{ type: "session_start", reason: "fork", previousSessionFile: parentSessionFile },
			createContext("child", childSessionFile),
			dir,
		);
		const loadedChild = loadSessionState({ sessionId: "child", sessionFile: childSessionFile }, dir);
		const loadedParent = loadSessionState({ sessionId: "parent", sessionFile: parentSessionFile }, dir);

		assert.equal(childState.sessionId, "child");
		assert.equal(childState.sessionFile, childSessionFile);
		assert.deepEqual(childState.activeWorktree, parentState.activeWorktree);
		assert.equal(childState.agentMode, "executor");
		assert.equal(childState.title, "Parent title");
		assert.deepEqual(loadedChild, childState);
		assert.deepEqual(loadedParent, parentState);
	});

	it("saves child defaults when the parent session cannot be read", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});
		const childSessionFile = path.join(dir, "child-missing-parent.jsonl");

		const childState = initializeCurrentSessionStateForEvent(
			{ type: "session_start", reason: "fork", previousSessionFile: path.join(dir, "missing-parent.jsonl") },
			createContext("child-missing-parent", childSessionFile),
			dir,
		);
		const childStateFileExists = await fs
			.access(buildSessionStatePath("child-missing-parent", dir))
			.then(() => true)
			.catch(() => false);

		assert.equal(childStateFileExists, true);
		assert.equal(childState.sessionId, "child-missing-parent");
		assert.equal(childState.sessionFile, childSessionFile);
		assert.equal(childState.activeWorktree, null);
		assert.equal(childState.agentMode, null);
		assert.equal(childState.title, null);
	});

	it("falls back to the child header parentSession when previousSessionFile is absent", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});
		const parentSessionFile = path.join(dir, "header-parent.jsonl");
		const childSessionFile = path.join(dir, "header-child.jsonl");
		await writeTranscriptHeader(parentSessionFile, "header-parent");
		saveSessionState(
			{
				...createDefaultSessionState({ sessionId: "header-parent", sessionFile: parentSessionFile }),
				agentMode: "planning",
				title: "Header parent title",
			},
			dir,
		);

		const childState = initializeCurrentSessionStateForEvent(
			{ type: "session_start", reason: "fork" },
			createContext("header-child", childSessionFile, parentSessionFile),
			dir,
		);

		assert.equal(childState.sessionId, "header-child");
		assert.equal(childState.agentMode, "planning");
		assert.equal(childState.title, "Header parent title");
	});
});
