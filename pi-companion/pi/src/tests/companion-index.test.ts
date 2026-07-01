import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerTasksAccess, type TasksState } from "pi-core/platform/tasks-access.ts";
import registerCompanion from "../companion-index.ts";
import { companionLiveSnapshotPath, companionSnapshotPath, defaultCompanionSnapshotDir } from "../snapshot.ts";

type Handler = (event: unknown, ctx: MockContext) => unknown;

interface MockContext {
	sessionManager: { getSessionId(): string };
	model: { id: string } | null;
}

const originalHome = process.env.HOME;
let tempHomes: string[] = [];

function createMockPi() {
	const handlers = new Map<string, Handler[]>();
	const pi = {
		on(eventName: string, handler: Handler) {
			handlers.set(eventName, [...(handlers.get(eventName) ?? []), handler]);
		},
	};
	return {
		pi: pi as unknown as ExtensionAPI,
		async emit(eventName: string, event: unknown = {}, ctx: MockContext = createContext()) {
			for (const handler of handlers.get(eventName) ?? []) {
				await handler(event, ctx);
			}
			return ctx;
		},
	};
}

function createContext(): MockContext {
	return {
		sessionManager: { getSessionId: () => "session/writer:1" },
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
	afterEach(() => {
		if (originalHome === undefined) {
			delete process.env.HOME;
		} else {
			process.env.HOME = originalHome;
		}
		delete process.env.BASECAMP_AGENT_DEPTH;
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
});
