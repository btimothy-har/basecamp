import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { registerWorkspaceService } from "pi-core/platform/workspace.ts";
import {
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "pi-core/state/index.ts";
import { SCRATCH_ROOT, WORKTREES_ROOT } from "pi-core/workspace/constants.ts";
import { WorkspaceRuntimeService } from "../service.ts";
import { registerWorkspaceSession } from "../session.ts";

const REPO_ROOT = "/repo";
// Derived from REMOTE_URL by resolveGitInfo: <org>/<name>, not the toplevel basename.
const REPO_IDENTITY = "test/repo";
const LABEL = "feature";
const BRANCH = "wt/feature";
const REMOTE_URL = "git@github.com:test/repo.git";
const WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_IDENTITY, LABEL);
const SCRATCH_DIR = path.join(SCRATCH_ROOT, REPO_IDENTITY);

interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

type ExecResult = { code: number; stdout: string; stderr: string };

function isWorkspaceEnvKey(key: string): boolean {
	return key.startsWith("BASECAMP_");
}

function restoreWorkspaceEnv(snapshot: Record<string, string | undefined>): void {
	for (const key of Object.keys(process.env)) {
		if (isWorkspaceEnvKey(key) && !(key in snapshot)) delete process.env[key];
	}
	for (const [key, value] of Object.entries(snapshot)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
}

function snapshotWorkspaceEnv(): Record<string, string | undefined> {
	return Object.fromEntries(
		Object.entries(process.env)
			.filter(([key]) => isWorkspaceEnvKey(key))
			.map(([key, value]) => [key, value]),
	);
}

function clearAgentDepthEnv(): void {
	delete process.env.BASECAMP_AGENT_DEPTH;
}

function gitWorktreeListOutput(worktreeDir = WORKTREE_DIR, branch = BRANCH): string {
	return [
		`worktree ${REPO_ROOT}`,
		"branch refs/heads/main",
		"",
		`worktree ${worktreeDir}`,
		`branch refs/heads/${branch}`,
		"",
	].join("\n");
}

function argsEqual(actual: string[], expected: string[]): boolean {
	return actual.length === expected.length && actual.every((arg, index) => arg === expected[index]);
}

function unexpectedExecCall(call: ExecCall): Error {
	return new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
}

function createContext(sessionId: string): ExtensionContext {
	return {
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
		},
	} as unknown as ExtensionContext;
}

function createWorkspaceSessionContext(sessionId: string, notifications: string[]): ExtensionContext {
	return {
		cwd: REPO_ROOT,
		hasUI: true,
		ui: {
			notify(message: string) {
				notifications.push(message);
			},
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
		},
	} as unknown as ExtensionContext;
}

function createPi(piOptions: { worktreeDir?: string; branch?: string } = {}): {
	pi: ExtensionAPI;
	calls: ExecCall[];
} {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			const call = { command, args, options };
			calls.push(call);

			if (command !== "git") throw unexpectedExecCall(call);
			if (argsEqual(args, ["rev-parse", "--show-toplevel"])) {
				return { code: 0, stdout: `${REPO_ROOT}\n`, stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${REMOTE_URL}\n`, stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
				return { code: 0, stdout: "origin/main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "branch", "--show-current"])) {
				return { code: 0, stdout: "main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "status", "--porcelain"])) {
				return { code: 0, stdout: "", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: gitWorktreeListOutput(piOptions.worktreeDir, piOptions.branch), stderr: "" };
			}

			throw unexpectedExecCall(call);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

function createSessionPi(options: { worktreeDir: string; branch: string }): {
	pi: ExtensionAPI;
	calls: ExecCall[];
	sessionStart: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>;
} {
	const { pi, calls } = createPi(options);
	let sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;
	const sessionPi = {
		...pi,
		registerFlag() {},
		getFlag() {
			return undefined;
		},
		on(event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) {
			if (event === "session_start") sessionStart = handler;
		},
	} as unknown as ExtensionAPI;
	return {
		pi: sessionPi,
		calls,
		sessionStart(event, ctx) {
			if (!sessionStart) throw new Error("session_start handler was not registered");
			return sessionStart(event, ctx);
		},
	};
}

async function initializeAndActivate(
	launchCwd: string,
): Promise<{ service: WorkspaceRuntimeService; calls: ExecCall[] }> {
	const { pi, calls } = createPi();
	const service = new WorkspaceRuntimeService(pi);
	await service.initialize({
		launchCwd,
		unsafeEditFlag: false,
		unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
	});
	await service.activateWorktree(LABEL);
	return { service, calls };
}

describe("WorkspaceRuntimeService effective cwd", () => {
	it("preserves protected repo subdirectory when activating an existing worktree", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
		});

		const launchCwd = path.join(REPO_ROOT, "packages", "app");
		const { service, calls } = await initializeAndActivate(launchCwd);

		assert.equal(service.getEffectiveCwd(), path.join(WORKTREE_DIR, "packages", "app"));
		assert.equal(service.current()?.activeWorktree?.created, false);
		assert.ok(
			calls.some(
				(call) => call.command === "git" && argsEqual(call.args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"]),
			),
		);
	});

	it("uses worktree root when launch cwd is outside protected root", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
		});

		const { service } = await initializeAndActivate("/outside");

		assert.equal(service.current()?.protectedRoot, REPO_ROOT);
		assert.equal(service.current()?.launchCwd, path.resolve("/outside"));
		assert.equal(service.getEffectiveCwd(), WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_DIR, WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_LABEL, LABEL);
	});

	it("writes active worktree metadata when current session state is initialized", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-workspace-state-"));
		t.after(async () => {
			resetCurrentSessionState();
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(stateDir, { recursive: true, force: true });
		});

		initializeCurrentSessionState(createContext("workspace-service-state"), stateDir);
		await initializeAndActivate(REPO_ROOT);

		const activeWorktree = getCurrentSessionState().activeWorktree;
		assert.deepEqual(activeWorktree, {
			version: 1,
			repoName: REPO_IDENTITY,
			repoRoot: REPO_ROOT,
			remoteUrl: REMOTE_URL,
			worktree: {
				kind: "git-worktree",
				label: LABEL,
				path: WORKTREE_DIR,
				branch: BRANCH,
				created: false,
			},
			updatedAt: activeWorktree?.updatedAt,
		});
		assert.match(activeWorktree?.updatedAt ?? "", /^\d{4}-\d{2}-\d{2}T/);
	});

	it("restores active worktree metadata from session state on resume", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-workspace-restore-"));
		const label = `restore-${process.pid}-${Date.now()}`;
		const branch = `wt/${label}`;
		const worktreeDir = path.join(WORKTREES_ROOT, REPO_IDENTITY, label);
		const notifications: string[] = [];
		t.after(async () => {
			resetCurrentSessionState();
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(stateDir, { recursive: true, force: true });
			await fs.rm(worktreeDir, { recursive: true, force: true });
		});

		await fs.mkdir(worktreeDir, { recursive: true });
		const ctx = createWorkspaceSessionContext("workspace-restore-state", notifications);
		saveSessionState(
			{
				...createDefaultSessionState({ sessionId: "workspace-restore-state", sessionFile: null }),
				activeWorktree: {
					version: 1,
					repoName: REPO_IDENTITY,
					repoRoot: REPO_ROOT,
					remoteUrl: REMOTE_URL,
					worktree: {
						kind: "git-worktree",
						label,
						path: worktreeDir,
						branch,
						created: false,
					},
					updatedAt: "2026-05-04T00:00:00.000Z",
				},
			},
			stateDir,
		);
		initializeCurrentSessionState(ctx, stateDir);

		const { pi, sessionStart } = createSessionPi({ worktreeDir, branch });
		const service = new WorkspaceRuntimeService(pi);
		registerWorkspaceService(service);
		registerWorkspaceSession(pi);

		await sessionStart({ type: "session_start", reason: "resume" }, ctx);

		assert.equal(service.current()?.activeWorktree?.label, label);
		assert.equal(service.current()?.activeWorktree?.path, worktreeDir);
		assert.equal(getCurrentSessionState().activeWorktree?.worktree.path, worktreeDir);
		assert.ok(notifications.includes(`basecamp: restored worktree → ${label}`));
	});
});
