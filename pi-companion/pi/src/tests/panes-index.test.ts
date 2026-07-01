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

describe("panes/registerPanes", () => {
	afterEach(() => {
		delete process.env.TMUX;
		delete process.env.TMUX_PANE;
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
		assert.equal(getPaneState().paneId, "%42");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("keeps companion active false, clears stale pane state, and does not publish pane status when ui is unavailable", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		const { pi, emit } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_start", {}, createContext({ hasUI: false }));

		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls, []);
	});

	it("clears stale pane state and publishes companion off when pane guards skip in a ui session", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		delete process.env.TMUX;
		const { pi, emit } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_start");

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

	it("reuses an existing pane on session start without execing tmux or checking dashboard availability", async () => {
		withTmuxEnv();
		setCompanionActive(false);
		const state = getPaneState();
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi(() => {
			throw new Error("unexpected exec");
		});
		registerPanes(pi);

		const ctx = await emit("session_start");

		assert.equal(execCalls.length, 0);
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(isCompanionActive(), true);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: "success:companion ✓" });
	});

	it("quit shutdown clears pane state, companion active, and pane status", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		const ctx = await emit("session_shutdown", { reason: "quit" });

		assert.deepEqual(execCalls.at(-1), { command: "tmux", args: ["kill-pane", "-t", "%8"] });
		assert.equal(getPaneState().paneId, null);
		assert.equal(isCompanionActive(), false);
		assert.deepEqual(ctx.ui.statusCalls.at(-1), { key: "basecamp.daemon.pane", value: undefined });
	});

	it("non-quit shutdown preserves pane state and companion active", async () => {
		setCompanionActive(true);
		const state = getPaneState();
		state.paneId = "%8";
		const { pi, emit, execCalls } = createMockPi();
		registerPanes(pi);

		await emit("session_shutdown", { reason: "reload" });

		assert.equal(execCalls.length, 0);
		assert.equal(getPaneState().paneId, "%8");
		assert.equal(isCompanionActive(), true);
	});
});
