import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
	initializeCurrentSessionState,
	resetCurrentSessionState,
	updateCurrentSessionState,
} from "#core/state/index.ts";
import { registerTasksAccess, type TasksState } from "#tasks/index.ts";
import { resetHerdrMetadataSeqForTest } from "../herdr/metadata.ts";
import registerCompanion from "../snapshot/index.ts";
import { companionLiveSnapshotPath, companionSnapshotPath, defaultCompanionSnapshotDir } from "../snapshot/model.ts";

type Handler = (event: unknown, ctx: MockContext) => unknown;
type Emit = (eventName: string, event?: unknown, ctx?: MockContext) => Promise<MockContext>;
type ExecResult = { code: number; stdout: string; stderr: string };
type ExecHandler = (command: string, args: string[]) => Promise<ExecResult> | ExecResult;

interface MockContext {
	sessionManager: {
		getSessionId(): string;
		getSessionFile(): string | null;
	};
	model: { id: string } | null;
}

const originalHome = process.env.HOME;
const activeEmitters = new Set<Emit>();
let tempHomes: string[] = [];

function createMockPi(execHandler: ExecHandler = () => ({ code: 0, stdout: "", stderr: "" })) {
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
	const emit: Emit = async (eventName, event = {}, ctx = createContext()) => {
		for (const handler of handlers.get(eventName) ?? []) {
			await handler(event, ctx);
		}
		return ctx;
	};
	activeEmitters.add(emit);
	return {
		pi: pi as unknown as ExtensionAPI,
		execCalls,
		emit,
	};
}

function createContext(): MockContext {
	return {
		sessionManager: {
			getSessionId: () => "session/writer:1",
			getSessionFile: () => null,
		},
		model: { id: "model-live" },
	};
}

function useTempHome(): string {
	const home = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-companion-home-"));
	tempHomes.push(home);
	process.env.HOME = home;
	return home;
}

function registerEmptyTasksAccess(): void {
	registerTasksAccess({
		getState: () => ({ goal: null, tasks: [] }),
		setNotes() {},
		activateGoalCycle() {},
		getPlanRef: () => null,
		getContext: () => null,
	});
}

describe("companion/registerCompanion", () => {
	afterEach(async () => {
		for (const emit of activeEmitters) {
			await emit("session_shutdown", { reason: "reload" });
		}
		activeEmitters.clear();

		if (originalHome === undefined) {
			delete process.env.HOME;
		} else {
			process.env.HOME = originalHome;
		}
		delete process.env.BASECAMP_AGENT_DEPTH;
		delete process.env.HERDR_ENV;
		delete process.env.HERDR_PANE_ID;
		delete process.env.HERDR_SOCKET_PATH;
		resetHerdrMetadataSeqForTest();
		resetCurrentSessionState();
		registerEmptyTasksAccess();
		for (const home of tempHomes) {
			fs.rmSync(home, { recursive: true, force: true });
		}
		tempHomes = [];
	});

	it("writes per-session and live snapshots on updates and removes both on quit", async () => {
		const home = useTempHome();
		process.env.BASECAMP_AGENT_DEPTH = "0";
		let tasksState: TasksState = { goal: "initial goal", tasks: [] };
		registerTasksAccess({
			getState: () => tasksState,
			setNotes() {},
			activateGoalCycle() {},
			getPlanRef: () => null,
			getContext: () => null,
		});
		const snapshotDir = defaultCompanionSnapshotDir(home);
		const perSessionPath = companionSnapshotPath("session/writer:1", snapshotDir);
		const livePath = companionLiveSnapshotPath(snapshotDir);
		const { pi, emit } = createMockPi();

		registerCompanion(pi);
		await emit("session_start");

		assert.equal(JSON.parse(fs.readFileSync(perSessionPath, "utf8")).goal, "initial goal");
		assert.equal(JSON.parse(fs.readFileSync(livePath, "utf8")).goal, "initial goal");

		tasksState = {
			goal: "updated goal",
			tasks: [
				{
					label: "Write live snapshot",
					description: "Write a process-scoped live snapshot",
					criteria: "Both snapshot files contain the update",
					notes: null,
					status: "completed",
					review: null,
				},
			],
		};
		await emit("tool_result", { isError: false, toolName: "update_goal" });

		const perSessionSnapshot = JSON.parse(fs.readFileSync(perSessionPath, "utf8"));
		const liveSnapshot = JSON.parse(fs.readFileSync(livePath, "utf8"));
		assert.equal(perSessionSnapshot.goal, "updated goal");
		assert.equal(liveSnapshot.goal, "updated goal");
		assert.deepEqual(liveSnapshot, perSessionSnapshot);

		await emit("session_shutdown", { reason: "quit" });

		assert.equal(fs.existsSync(perSessionPath), false);
		assert.equal(fs.existsSync(livePath), false);
	});

	it("reports Herdr metadata on session start and task tool results", async () => {
		useTempHome();
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
		let tasksState: TasksState = {
			goal: "initial goal",
			tasks: [
				{
					label: "Start task",
					description: "Initial task",
					criteria: "Metadata reports the active task",
					notes: null,
					status: "active",
					review: null,
				},
			],
		};
		registerTasksAccess({
			getState: () => tasksState,
			setNotes() {},
			activateGoalCycle() {},
			getPlanRef: () => null,
			getContext: () => null,
		});
		const { pi, emit, execCalls } = createMockPi();

		registerCompanion(pi);
		await emit("session_start");
		tasksState = {
			goal: "updated goal",
			tasks: [
				{
					label: "Updated task",
					description: "Updated task",
					criteria: "Metadata reports the updated active task",
					notes: null,
					status: "active",
					review: null,
				},
			],
		};
		await emit("tool_result", { isError: false, toolName: "start_task" });

		assert.equal(execCalls.length, 2);
		assert.deepEqual(execCalls[0], {
			command: "herdr",
			args: [
				"pane",
				"report-metadata",
				"w8:p1",
				"--source",
				"basecamp.pi",
				"--display-agent",
				"pi",
				"--title",
				"session/writer:1",
				"--custom-status",
				"Start task",
				"--seq",
				"1",
			],
		});
		const secondCall = execCalls[1];
		assert.ok(secondCall);
		assert.deepEqual(secondCall.args.slice(0, 3), ["pane", "report-metadata", "w8:p1"]);
		assert.deepEqual(secondCall.args.slice(-2), ["--seq", "2"]);
		assert.equal(secondCall.args[secondCall.args.indexOf("--custom-status") + 1], "Updated task");
	});

	it("reports Herdr metadata when the session title changes", async () => {
		useTempHome();
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
		registerEmptyTasksAccess();
		const ctx = createContext();
		initializeCurrentSessionState(ctx as unknown as ExtensionContext);
		const { pi, emit, execCalls } = createMockPi();

		registerCompanion(pi);
		await emit("session_start", {}, ctx);
		updateCurrentSessionState({ title: "Manual title" });

		assert.equal(execCalls.length, 2);
		const titleArgIndex = execCalls[1]!.args.indexOf("--title") + 1;
		assert.equal(execCalls[1]!.args[titleArgIndex], "Manual title");
		assert.deepEqual(execCalls[1]!.args.slice(-2), ["--seq", "2"]);
	});

	it("swallows Herdr reporting failures without blocking snapshot writes", async () => {
		const home = useTempHome();
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
		registerEmptyTasksAccess();
		const snapshotDir = defaultCompanionSnapshotDir(home);
		const perSessionPath = companionSnapshotPath("session/writer:1", snapshotDir);
		const { pi, emit } = createMockPi(() => {
			throw new Error("Herdr unavailable");
		});

		registerCompanion(pi);
		await emit("session_start");

		assert.equal(JSON.parse(fs.readFileSync(perSessionPath, "utf8")).sessionId, "session/writer:1");
	});
});
