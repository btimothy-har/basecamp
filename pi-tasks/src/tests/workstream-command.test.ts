import assert from "node:assert/strict";
import * as fs from "node:fs";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { registerWorkstreamCommand, type WorkstreamCommandDeps } from "../workstreams/command.ts";
import type { WorkstreamLaunchRecord } from "../workstreams/launch-state.ts";

interface RegisteredCommand {
	description: string;
	handler(args: string | undefined, ctx: ExtensionContext): Promise<void>;
}

class FakePi {
	readonly commands = new Map<string, RegisteredCommand>();
	readonly userMessages: string[] = [];

	registerCommand(name: string, command: RegisteredCommand): void {
		this.commands.set(name, command);
	}

	sendUserMessage(text: string): void {
		this.userMessages.push(text);
	}
}

function makeCtx(): { ctx: ExtensionContext; notices: { message: string; level: string }[] } {
	const notices: { message: string; level: string }[] = [];
	const ctx = {
		hasUI: true,
		ui: {
			notify(message: string, level: string) {
				notices.push({ message, level });
			},
		},
		sessionManager: { getSessionId: () => "session-abc" },
	} as unknown as ExtensionContext;
	return { ctx, notices };
}

function makeRecord(overrides: Partial<WorkstreamLaunchRecord> = {}): WorkstreamLaunchRecord {
	return {
		id: "launch-workstream-too",
		fingerprint: "fp",
		repo: "org/repo",
		source: { dossierPath: "/graph/pages/Dossier.md", repoPagePath: "/graph/pages/Repo.md" },
		workstream: {
			label: "Launch Workstream Too",
			brief: "Implement the launch workstream tool.",
			constraints: "Stay in scope.",
		},
		worktree: { label: "wt-bt/8e95-launch-workstream-too", path: "/worktrees/x", branch: "bt/x" },
		agent: {},
		setup: { status: "succeeded" },
		herdr: { status: "succeeded" },
		launch: { status: "succeeded" },
		createdAt: "2026-07-03T00:00:00.000Z",
		updatedAt: "2026-07-03T00:00:00.000Z",
		...overrides,
	};
}

function makeDeps(overrides: Partial<WorkstreamCommandDeps> = {}) {
	const stampCalls: { id: string; handle: string }[] = [];
	let record: WorkstreamLaunchRecord | null = makeRecord();
	let handle: string | null = "swift-otter-1a2b3c";
	const deps: WorkstreamCommandDeps = {
		getWorkspaceState: () => ({ repo: { isRepo: true, name: "org/repo" } }) as unknown as WorkspaceState,
		launchStatePath: () => "/tmp/launch-index.json",
		findById: (_filePath, _id, _repo) => record,
		stampHandle: (_filePath, id, h) => {
			stampCalls.push({ id, handle: h });
			return record;
		},
		deriveHandle: () => handle,
		...overrides,
	};
	return {
		deps,
		stampCalls,
		setRecord(value: WorkstreamLaunchRecord | null) {
			record = value;
		},
		setHandle(value: string | null) {
			handle = value;
		},
	};
}

async function run(pi: FakePi, args: string | undefined, ctx: ExtensionContext) {
	const command = pi.commands.get("workstream");
	assert.ok(command, "workstream command should be registered");
	await command.handler(args, ctx);
}

describe("/workstream command", () => {
	it("loads the brief, injects it, and stamps this session's handle", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		registerWorkstreamCommand(pi as unknown as ExtensionAPI, harness.deps);
		const { ctx } = makeCtx();

		await run(pi, "launch-workstream-too", ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(pi.userMessages[0]!, /Launch Workstream Too/);
		assert.match(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.deepEqual(harness.stampCalls, [{ id: "launch-workstream-too", handle: "swift-otter-1a2b3c" }]);
	});

	it("returns a usage error when no id is given", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		registerWorkstreamCommand(pi as unknown as ExtensionAPI, harness.deps);
		const { ctx, notices } = makeCtx();

		await run(pi, "  ", ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Usage: \/workstream <id>/);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports a clear error for an unknown id without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setRecord(null);
		registerWorkstreamCommand(pi as unknown as ExtensionAPI, harness.deps);
		const { ctx, notices } = makeCtx();

		await run(pi, "missing-id", ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /No staged workstream "missing-id"/);
		assert.equal(notices[0]?.level, "error");
	});

	it("degrades gracefully when the handle cannot be derived", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setHandle(null);
		registerWorkstreamCommand(pi as unknown as ExtensionAPI, harness.deps);
		const { ctx } = makeCtx();

		await run(pi, "launch-workstream-too", ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(pi.userMessages[0]!, /agent handle could not be determined/);
		assert.equal(harness.stampCalls.length, 0);
	});

	it("warns when the handle is derived but cannot be persisted", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			stampHandle: () => {
				throw new Error("disk full");
			},
		});
		registerWorkstreamCommand(pi as unknown as ExtensionAPI, harness.deps);
		const { ctx, notices } = makeCtx();

		await run(pi, "launch-workstream-too", ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /agent handle was derived as `swift-otter-1a2b3c`/);
		assert.match(pi.userMessages[0]!, /could not be persisted/);
		assert.doesNotMatch(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.doesNotMatch(pi.userMessages[0]!, /agent handle could not be determined/);
		assert.match(notices[0]?.message ?? "", /could not persist it to the workstream record/);
		assert.equal(notices[0]?.level, "error");
		assert.equal(harness.stampCalls.length, 0);
	});

	it("is wired from pi-tasks/index.ts", () => {
		const indexSource = fs.readFileSync(new URL("../../index.ts", import.meta.url), "utf8");
		assert.match(indexSource, /import \{ registerWorkstreamCommand \} from "\.\/src\/workstreams\/command\.ts";/);
		assert.match(indexSource, /registerWorkstreamCommand\(pi\);/);
	});
});
