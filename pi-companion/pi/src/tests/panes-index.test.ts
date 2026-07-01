import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionPackage from "../../index.ts";
import registerPanes from "../panes-index.ts";
import { getPaneState, isCompanionActive, setCompanionActive } from "../panes-state.ts";
import { companionLiveSnapshotPath } from "../snapshot.ts";

type Handler = (event: unknown, ctx: MockContext) => unknown;

type ExecResult = { code: number; stdout: string; stderr: string };

type ExecHandler = (command: string, args: string[]) => Promise<ExecResult> | ExecResult;

type StatusSetCall = { key: string; value: string | undefined };

interface MockContext {
	hasUI: boolean;
	sessionManager: { getSessionId(): string };
	ui: {
		notifications: Array<{ message: string; level: string }>;
		statusCalls: StatusSetCall[];
		theme: { fg(color: string, text: string): string };
		notify(message: string, level: string): void;
		setStatus(key: string, value: string | undefined): void;
	};
}

function resetPaneState(): void {
	const state = getPaneState();
	state.provider = null;
	state.paneId = null;
	setCompanionActive(false);
}

function createContext(overrides: Partial<MockContext> = {}): MockContext {
	const notifications: Array<{ message: string; level: string }> = [];
	const statusCalls: StatusSetCall[] = [];
	return {
		hasUI: true,
		sessionManager: { getSessionId: () => "session-1" },
		ui: {
			notifications,
			statusCalls,
			theme: { fg: (color: string, text: string) => `${color}:${text}` },
			notify(message: string, level: string) {
				notifications.push({ message, level });
			},
			setStatus(key: string, value: string | undefined) {
				statusCalls.push({ key, value });
			},
		},
		...overrides,
	};
}

function createMockPi(execHandler: ExecHandler = () => ({ code: 0, stdout: "%9\n", stderr: "" })) {
	const handlers = new Map<string, Handler[]>();
	const execCalls: Array<{ command: string; args: string[] }> = [];
	const pi = {
		on(eventName: string, handler: Handler) {
			handlers.set(eventName, [...(handlers.get(eventName) ?? []), handler]);
		},
		async exec(command: string, args: string[]) {
			execCalls.push({ command, args });
			return execHandler(command, args);
		},
	};
	return {
		pi: pi as unknown as ExtensionAPI,
		execCalls,
		registeredEvents: () => [...handlers.keys()],
		async emit(eventName: string, event: unknown = {}, ctx: MockContext = createContext()) {
			for (const handler of handlers.get(eventName) ?? []) {
				await handler(event, ctx);
			}
			return ctx;
		},
	};
}

function withTmuxEnv(): void {
	process.env.TMUX = "/tmp/tmux.sock,123,0";
	process.env.TMUX_PANE = "%1";
	process.env.BASECAMP_AGENT_DEPTH = "0";
}

function withHerdrEnv(): void {
	process.env.HERDR_ENV = "1";
	process.env.HERDR_PANE_ID = "w8:p1";
	process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
	process.env.BASECAMP_AGENT_DEPTH = "0";
}

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

	it("package registration initializes companion active and registers analysis", () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		setCompanionActive(true);
		const { pi, registeredEvents } = createMockPi();

		registerCompanionPackage(pi);

		assert.equal(isCompanionActive(), false);
		assert.ok(registeredEvents().includes("agent_end"));
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

	it("reuses a live existing Herdr pane without splitting or checking dashboard availability", async () => {
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

	it("reuses a live existing pane after a liveness check without splitting or checking dashboard availability", async () => {
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
