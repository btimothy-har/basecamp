import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	ensureCurrentSessionStateForEvent,
	getCurrentSessionState,
	getCurrentSessionStateIfInitialized,
	initializeCurrentSessionState,
	loadSessionState,
	onCurrentSessionTitleChange,
	resetCurrentSessionState,
	updateCurrentSessionState,
} from "../index.ts";
import { createContext, createTempDir } from "./session-state-harness.ts";

describe("current session state", () => {
	it("returns null from the non-throwing getter before initialization", () => {
		resetCurrentSessionState();

		assert.equal(getCurrentSessionStateIfInitialized(), null);
	});

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

	it("notifies listeners only when the current title changes", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});
		const seen: string[] = [];
		const unsubscribe = onCurrentSessionTitleChange((title, state) => {
			seen.push(`${state.sessionId}:${title ?? "null"}`);
		});
		t.after(() => {
			unsubscribe();
		});

		initializeCurrentSessionState(createContext("title-listener"), dir);
		updateCurrentSessionState({ title: "First title" });
		updateCurrentSessionState({ agentMode: "planning" });
		updateCurrentSessionState({ title: "First title" });
		updateCurrentSessionState({ title: null });
		unsubscribe();
		updateCurrentSessionState({ title: "After unsubscribe" });

		assert.deepEqual(seen, ["title-listener:First title", "title-listener:null"]);
	});
});

describe("ensureCurrentSessionStateForEvent", () => {
	it("initializes when no state exists yet (consumer runs before the owner)", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});
		resetCurrentSessionState();

		const ensured = ensureCurrentSessionStateForEvent(
			{ type: "session_start", reason: "reload" },
			createContext("ensure-reload", "/tmp/ensure-reload.json"),
			dir,
		);

		assert.equal(ensured.sessionId, "ensure-reload");
		assert.equal(getCurrentSessionState().sessionId, "ensure-reload");
	});

	it("reuses existing state for the same session without clobbering mutations", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});

		const event = { type: "session_start", reason: "reload" } as const;
		const ctx = createContext("ensure-shared", "/tmp/ensure-shared.json");

		ensureCurrentSessionStateForEvent(event, ctx, dir);
		updateCurrentSessionState({ title: "set by first consumer" });

		// A second consumer (or the owner) ensuring the same session must not reset state.
		const second = ensureCurrentSessionStateForEvent(event, ctx, dir);

		assert.equal(second.title, "set by first consumer");
		assert.equal(getCurrentSessionState().title, "set by first consumer");
	});

	it("re-initializes when the session identity changes", async (t) => {
		const dir = await createTempDir(t);
		t.after(() => {
			resetCurrentSessionState();
		});

		ensureCurrentSessionStateForEvent(
			{ type: "session_start", reason: "reload" },
			createContext("first-session", "/tmp/first-session.json"),
			dir,
		);
		updateCurrentSessionState({ title: "stale" });

		const next = ensureCurrentSessionStateForEvent(
			{ type: "session_start", reason: "resume" },
			createContext("second-session", "/tmp/second-session.json"),
			dir,
		);

		assert.equal(next.sessionId, "second-session");
		assert.equal(next.title, null);
	});
});
