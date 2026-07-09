import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import registerPanes from "../panes-index.ts";
import { getPaneState, isCompanionActive, setCompanionActive } from "../panes-state.ts";
import { companionLiveSnapshotPath } from "../snapshot.ts";
import { createContext, createMockPi, resetPaneState, withHerdrEnv, withTmuxEnv } from "./panes-harness.ts";

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

	it("sets companion active true and launches dashboard with the live snapshot path after creating a pane", async () => {
		withTmuxEnv();
		const { pi, emit, execCalls } = createMockPi((command) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "%42\n", stderr: "" };
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		const splitCall = execCalls.find((call) => call.command === "tmux");
		assert.ok(splitCall);
		assert.equal(splitCall.args[0], "split-window");
		assert.ok((splitCall.args.at(-1) ?? "").includes(`--snapshot '${companionLiveSnapshotPath()}'`));
		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%42");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("prefers Herdr over tmux when required Herdr env is available", async () => {
		withTmuxEnv();
		withHerdrEnv();
		const { pi, emit, execCalls } = createMockPi((command, args) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			if (command === "herdr" && args[1] === "split") {
				return { code: 0, stdout: JSON.stringify({ pane: { id: "w8:p2" } }), stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" };
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.equal(
			execCalls.some((call) => call.command === "tmux"),
			false,
		);
		const splitCall = execCalls.find((call) => call.command === "herdr" && call.args[1] === "split");
		assert.ok(splitCall);
		assert.deepEqual(splitCall.args, [
			"pane",
			"split",
			"w8:p1",
			"--direction",
			"right",
			"--cwd",
			process.cwd(),
			"--no-focus",
		]);
		const runCall = execCalls.find((call) => call.command === "herdr" && call.args[1] === "run");
		assert.ok(runCall);
		assert.equal(runCall.args[2], "w8:p2");
		assert.ok((runCall.args[3] ?? "").includes(`--snapshot '${companionLiveSnapshotPath()}'`));
		assert.equal(getPaneState().provider, "herdr");
		assert.equal(getPaneState().paneId, "w8:p2");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("falls back to tmux when Herdr env is incomplete", async () => {
		withTmuxEnv();
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		const { pi, emit, execCalls } = createMockPi((command) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "%42\n", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(
			execCalls.some((call) => call.command === "herdr"),
			false,
		);
		const splitCall = execCalls.find((call) => call.command === "tmux" && call.args[0] === "split-window");
		assert.ok(splitCall);
		assert.equal(getPaneState().provider, "tmux");
		assert.equal(getPaneState().paneId, "%42");
		assert.equal(isCompanionActive(), true);
	});

	it("keeps companion active false, clears stale pane state, and does not publish pane status when ui is unavailable", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		const { pi, emit } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_start", {}, createContext({ hasUI: false }));

		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls, []);
	});

	it("clears stale pane state and publishes companion off when pane guards skip in a ui session", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.provider = "tmux";
		state.paneId = "%8";
		delete process.env.TMUX;
		const { pi, emit } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "muted:companion off" });
	});

	it("clears stale pane state and publishes companion off when companion dashboard is unavailable", async () => {
		withTmuxEnv();
		setCompanionActive(true);
		const { pi, emit } = createMockPi((command) => {
			assert.equal(command, "basecamp");
			return { code: 1, stdout: "", stderr: "missing" };
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "muted:companion off" });
	});

	it("clears companion active when split fails", async () => {
		withTmuxEnv();
		setCompanionActive(true);
		const { pi, emit } = createMockPi((command) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			throw new Error("split failed");
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
	});

	it("clears companion active when split returns no pane id", async () => {
		withTmuxEnv();
		setCompanionActive(true);
		const { pi, emit } = createMockPi((command) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "created pane", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().provider, null);
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
	});
});
