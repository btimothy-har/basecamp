import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	createDefaultSessionState,
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
	saveSessionState,
} from "../../session/state/index.ts";
import { WORKTREES_ROOT } from "../constants.ts";
import { registerWorkspaceRuntime, resetWorkspaceRuntimeForTesting } from "../runtime.ts";
import { registerWorkspaceSession } from "../session.ts";
import {
	argsEqual,
	BRANCH,
	clearAgentDepthEnv,
	createContext,
	createSessionPi,
	createWorkspaceSessionContext,
	initializeAndActivate,
	LABEL,
	REMOTE_URL,
	REPO_IDENTITY,
	REPO_ROOT,
	restoreWorkspaceEnv,
	SCRATCH_DIR,
	snapshotWorkspaceEnv,
	WORKTREE_DIR,
} from "./service-harness.ts";

describe("WorkspaceRuntimeService effective cwd", () => {
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

	it("skips resume restore when init already recognized the active worktree", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		const stateDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-workspace-recognized-restore-"));
		const notifications: string[] = [];
		t.after(async () => {
			resetCurrentSessionState();
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(stateDir, { recursive: true, force: true });
		});

		const ctx = createWorkspaceSessionContext(
			"workspace-recognized-restore-state",
			notifications,
			path.join(WORKTREE_DIR, "packages", "app"),
		);
		saveSessionState(
			{
				...createDefaultSessionState({ sessionId: "workspace-recognized-restore-state", sessionFile: null }),
				activeWorktree: {
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
					updatedAt: "2026-05-04T00:00:00.000Z",
				},
			},
			stateDir,
		);
		initializeCurrentSessionState(ctx, stateDir);

		const { pi, calls, sessionStart } = createSessionPi({
			worktreeDir: WORKTREE_DIR,
			branch: BRANCH,
			linkedWorktree: true,
		});
		resetWorkspaceRuntimeForTesting();
		const service = registerWorkspaceRuntime(pi);
		registerWorkspaceSession(pi);

		await sessionStart({ type: "session_start", reason: "resume" }, ctx);

		assert.equal(service.current()?.protectedRoot, REPO_ROOT);
		assert.equal(service.current()?.activeWorktree?.path, WORKTREE_DIR);
		assert.equal(getCurrentSessionState().activeWorktree?.worktree.path, WORKTREE_DIR);
		assert.deepEqual(notifications, []);
		assert.equal(
			calls.some((call) => call.command === "git" && argsEqual(call.args, ["-C", REPO_ROOT, "status", "--porcelain"])),
			false,
		);
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
		resetWorkspaceRuntimeForTesting();
		const service = registerWorkspaceRuntime(pi);
		registerWorkspaceSession(pi);

		await sessionStart({ type: "session_start", reason: "resume" }, ctx);

		assert.equal(service.current()?.activeWorktree?.label, label);
		assert.equal(service.current()?.activeWorktree?.path, worktreeDir);
		assert.equal(getCurrentSessionState().activeWorktree?.worktree.path, worktreeDir);
		assert.ok(notifications.includes(`basecamp: restored worktree → ${label}`));
	});
});
