import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import registerPanes from "../panes/index.ts";
import { getPaneState, isCompanionActive, setCompanionActive } from "../panes/state.ts";
import { createMockPi, resetPaneState, withHerdrEnv, withTmuxEnv } from "./panes-harness.ts";

describe("panes/registerPanes", () => {
	afterEach(() => {
		delete process.env.TMUX;
		delete process.env.TMUX_PANE;
		delete process.env.HERDR_ENV;
		delete process.env.HERDR_PANE_ID;
		delete process.env.HERDR_SOCKET_PATH;
		delete process.env.BASECAMP_AGENT_DEPTH;
		resetPaneState();
	});

	it("reuses a live existing Herdr pane without splitting or checking TUI availability", async () => {
		withHerdrEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "herdr";
		state.paneId = "w8:p2";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "herdr" && args[1] === "get") {
				return { code: 0, stdout: JSON.stringify({ pane: { id: "w8:p2" } }), stderr: "" };
			}
			throw new Error("unexpected exec");
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.deepEqual(execCalls, [{ command: "herdr", args: ["pane", "get", "w8:p2"] }]);
		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p2");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("recreates the Herdr pane when the stored pane id is definitely gone", async () => {
		withHerdrEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "herdr";
		state.paneId = "w8:p2";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "herdr" && args[1] === "get") return { code: 1, stdout: "", stderr: "pane not found" };
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			if (command === "herdr" && args[1] === "split") {
				return { code: 0, stdout: JSON.stringify({ pane: { id: "w8:p3" } }), stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p3");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(
			execCalls.filter((call) => call.command === "herdr").map((call) => call.args[1]),
			["get", "split", "run"],
		);
	});

	it("keeps the existing Herdr pane when the liveness check is inconclusive", async () => {
		withHerdrEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "herdr";
		state.paneId = "w8:p2";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "herdr" && args[1] === "get") throw new Error("Herdr unavailable");
			throw new Error("unexpected exec");
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.deepEqual(execCalls, [{ command: "herdr", args: ["pane", "get", "w8:p2"] }]);
		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p2");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("replaces stale tmux state when Herdr becomes the active provider", async () => {
		withHerdrEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			if (command === "herdr" && args[1] === "split") {
				return { code: 0, stdout: JSON.stringify({ pane: { id: "w8:p2" } }), stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(
			execCalls.some((call) => call.command === "tmux"),
			false,
		);
		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p2");
		assert.equal(isCompanionActive(), true);
	});

	it("reuses a live existing pane after a liveness check without splitting or checking TUI availability", async () => {
		withTmuxEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "tmux" && args[0] === "list-panes") return { code: 0, stdout: "%1\n%8\n", stderr: "" };
			throw new Error("unexpected exec");
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.deepEqual(execCalls, [{ command: "tmux", args: ["list-panes", "-a", "-F", "#{pane_id}"] }]);
		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("recreates the pane when the stored pane id is no longer alive", async () => {
		withTmuxEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "tmux" && args[0] === "list-panes") return { code: 0, stdout: "%1\n%2\n", stderr: "" };
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "%42\n", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%42");
		assert.equal(isCompanionActive(), true);
		const tmuxCommands = execCalls.filter((call) => call.command === "tmux").map((call) => call.args[0]);
		assert.deepEqual(tmuxCommands, ["list-panes", "split-window"]);
		assert.ok(execCalls.some((call) => call.command === "basecamp"));
	});

	it("keeps the existing pane when the liveness check is inconclusive", async () => {
		withTmuxEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "tmux" && args[0] === "list-panes") throw new Error("tmux unavailable");
			throw new Error("unexpected exec");
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(isCompanionActive(), true);
		assert.ok(execCalls.every((call) => call.args[0] !== "split-window"));
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("quit shutdown clears pane state, companion active, and pane status", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_shutdown", { reason: "quit" });

		assert.deepEqual(execCalls.at(-1), { command: "tmux", args: ["kill-pane", "-t", "%8"] });
		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: undefined });
	});

	it("quit shutdown closes a stored Herdr pane", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "herdr";
		state.paneId = "w8:p2";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_shutdown", { reason: "quit" });

		assert.deepEqual(execCalls.at(-1), { command: "herdr", args: ["pane", "close", "w8:p2"] });
		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: undefined });
	});

	it("non-quit shutdown preserves pane state and companion active", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		await emit("session_shutdown", { reason: "reload" });

		assert.equal(execCalls.length, 0);
		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(isCompanionActive(), true);
	});

	it("non-quit shutdown preserves a stored Herdr pane", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "herdr";
		state.paneId = "w8:p2";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		await emit("session_shutdown", { reason: "reload" });

		assert.equal(execCalls.length, 0);
		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p2");
		assert.equal(isCompanionActive(), true);
	});
});
