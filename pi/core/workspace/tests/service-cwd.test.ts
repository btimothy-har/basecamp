import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import { WorkspaceRuntimeService } from "../runtime.ts";
import {
	argsEqual,
	BRANCH,
	clearAgentDepthEnv,
	createLinkedWorktreePi,
	createPi,
	initializeAndActivate,
	LABEL,
	REPO_ROOT,
	restoreWorkspaceEnv,
	SCRATCH_DIR,
	snapshotWorkspaceEnv,
	WORKTREE_DIR,
} from "./service-harness.ts";

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

	it("recognizes a linked worktree launch as the active worktree", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
		});

		const { pi, calls } = createPi({ linkedWorktree: true });
		const service = new WorkspaceRuntimeService(pi);
		const result = await service.initialize({
			launchCwd: path.join(WORKTREE_DIR, "packages", "app"),
			unsafeEditFlag: false,
			unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
		});

		assert.equal(result.state.protectedRoot, REPO_ROOT);
		assert.equal(result.state.repo?.root, REPO_ROOT);
		assert.deepEqual(result.state.activeWorktree, {
			kind: "git-worktree",
			label: LABEL,
			path: WORKTREE_DIR,
			branch: BRANCH,
			created: false,
		});
		assert.equal(service.current()?.activeWorktree?.path, WORKTREE_DIR);
		assert.equal(service.getEffectiveCwd(), WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_DIR, WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_LABEL, LABEL);
		assert.ok(
			calls.some(
				(call) => call.command === "git" && argsEqual(call.args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"]),
			),
		);
		assert.equal(
			calls.some((call) => call.command === "git" && argsEqual(call.args, ["-C", REPO_ROOT, "status", "--porcelain"])),
			false,
		);
	});

	it("falls back to the directory basename for a linked worktree outside the worktrees root", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
		});

		const externalWorktree = path.resolve("/external/my-feature");
		const { pi } = createLinkedWorktreePi({ toplevel: externalWorktree, branch: "feature-x" });
		const service = new WorkspaceRuntimeService(pi);
		const result = await service.initialize({
			launchCwd: externalWorktree,
			unsafeEditFlag: false,
			unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
		});

		assert.equal(result.state.protectedRoot, REPO_ROOT);
		assert.deepEqual(result.state.activeWorktree, {
			kind: "git-worktree",
			label: "my-feature",
			path: externalWorktree,
			branch: "feature-x",
			created: false,
		});
		assert.equal(service.getEffectiveCwd(), externalWorktree);
		assert.equal(process.env.BASECAMP_WORKTREE_DIR, externalWorktree);
		assert.equal(process.env.BASECAMP_WORKTREE_LABEL, "my-feature");
	});

	it("recognizes a detached-HEAD linked worktree with a detached branch", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
		});

		const { pi } = createLinkedWorktreePi({ toplevel: WORKTREE_DIR, branch: null });
		const service = new WorkspaceRuntimeService(pi);
		const result = await service.initialize({
			launchCwd: WORKTREE_DIR,
			unsafeEditFlag: false,
			unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
		});

		assert.equal(result.state.protectedRoot, REPO_ROOT);
		assert.deepEqual(result.state.activeWorktree, {
			kind: "git-worktree",
			label: LABEL,
			path: WORKTREE_DIR,
			branch: "detached",
			created: false,
		});
		assert.equal(process.env.BASECAMP_WORKTREE_LABEL, LABEL);
	});
});
