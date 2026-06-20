import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionPackage from "../../index.ts";
import registerPanes from "../panes-index.ts";
import { getPaneState, isCompanionActive, setCompanionActive } from "../panes-state.ts";

type Handler = (event: unknown, ctx: MockContext) => unknown;

type ExecResult = { code: number; stdout: string; stderr: string };

type ExecHandler = (command: string, args: string[]) => Promise<ExecResult> | ExecResult;

interface MockContext {
	hasUI: boolean;
	sessionManager: { getSessionId(): string };
	ui: { notifications: Array<{ message: string; level: string }>; notify(message: string, level: string): void };
}

function resetPaneState(): void {
	const state = getPaneState();
	state.paneId = null;
	state.currentCwd = null;
	state.currentSnapshot = null;
	state.unsubscribeWorkspace?.();
	state.unsubscribeWorkspace = null;
	setCompanionActive(false);
}

function createContext(overrides: Partial<MockContext> = {}): MockContext {
	const notifications: Array<{ message: string; level: string }> = [];
	return {
		hasUI: true,
		sessionManager: { getSessionId: () => "session-1" },
		ui: {
			notifications,
			notify(message: string, level: string) {
				notifications.push({ message, level });
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

describe("panes/registerPanes", () => {
	afterEach(() => {
		delete process.env.TMUX;
		delete process.env.TMUX_PANE;
		delete process.env.BASECAMP_AGENT_DEPTH;
		resetPaneState();
	});

	it("package registration initializes companion active to false", () => {
		setCompanionActive(true);
		const { pi } = createMockPi();

		registerCompanionPackage(pi);

		assert.equal(isCompanionActive(), false);
	});

	it("sets companion active true after creating and storing a pane id", async () => {
		withTmuxEnv();
		const { pi, emit } = createMockPi((command) => {
			if (command === "basecamp") return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "%42\n", stderr: "" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().paneId, "%42");
		assert.equal(isCompanionActive(), true);
	});

	it("keeps companion active false when pane guards skip", async () => {
		setCompanionActive(true);
		const { pi, emit } = createMockPi();
		registerPanes(pi);

		await emit("session_start", {}, createContext({ hasUI: false }));

		assert.equal(isCompanionActive(), false);
	});

	it("keeps companion active false when companion dashboard is unavailable", async () => {
		withTmuxEnv();
		setCompanionActive(true);
		const { pi, emit } = createMockPi((command) => {
			assert.equal(command, "basecamp");
			return { code: 1, stdout: "", stderr: "missing" };
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
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

		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
	});

	it("clears pane state and companion active when respawn of an existing pane fails", async () => {
		withTmuxEnv();
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		state.currentCwd = "/old";
		state.currentSnapshot = "/old-snapshot.json";
		const { pi, emit } = createMockPi((command) => {
			assert.equal(command, "tmux");
			throw new Error("respawn failed");
		});
		registerPanes(pi);

		await emit("session_start");

		assert.equal(getPaneState().paneId, null);
		assert.equal(getPaneState().currentCwd, null);
		assert.equal(getPaneState().currentSnapshot, null);
		assert.equal(isCompanionActive(), false);
	});

	it("quit shutdown clears pane state and companion active", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		state.currentCwd = "/cwd";
		state.currentSnapshot = "/snapshot.json";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		await emit("session_shutdown", { reason: "quit" });

		assert.deepEqual(execCalls.at(-1), { command: "tmux", args: ["kill-pane", "-t", "%8"] });
		assert.equal(getPaneState().paneId, null);
		assert.equal(getPaneState().currentCwd, null);
		assert.equal(getPaneState().currentSnapshot, null);
		assert.equal(isCompanionActive(), false);
	});

	it("non-quit shutdown preserves pane state and companion active", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		state.currentCwd = "/cwd";
		state.currentSnapshot = "/snapshot.json";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		await emit("session_shutdown", { reason: "reload" });

		assert.equal(execCalls.length, 0);
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(getPaneState().currentCwd, "/cwd");
		assert.equal(getPaneState().currentSnapshot, "/snapshot.json");
		assert.equal(isCompanionActive(), true);
	});
});
