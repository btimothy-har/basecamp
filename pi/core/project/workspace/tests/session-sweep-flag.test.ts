import assert from "node:assert/strict";
import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "#core/git/constants.ts";
import { registerWorkspaceRuntime, resetWorkspaceRuntimeForTesting } from "#core/project/workspace/runtime.ts";
import { registerWorkspaceSession } from "#core/project/workspace/session.ts";
import {
	argsEqual,
	clearAgentDepthEnv,
	createWorkspaceSessionContext,
	REMOTE_URL,
	REPO_IDENTITY,
	REPO_ROOT,
	restoreWorkspaceEnv,
	SCRATCH_DIR,
	snapshotWorkspaceEnv,
} from "./service-harness.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

const ok = (stdout: string): ExecResult => ({ code: 0, stdout, stderr: "" });

interface SweepState {
	removed: boolean;
	removeCalls: number;
	unlockCalls: number;
}

/**
 * Git mock for the --nc flag test: a cold (unlocked), clean session worktree is registered
 * with git — exactly what the cold backstop sweep reaps at session start. `remove` deletes
 * the real directory, so a skipped sweep is observable both in mock state and on disk.
 */
function sweepPi(
	residueDir: string,
	flags: Record<string, boolean | string | undefined>,
): {
	pi: ExtensionAPI;
	state: SweepState;
	sessionStart: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>;
} {
	const state: SweepState = { removed: false, removeCalls: 0, unlockCalls: 0 };

	function listOutput(): string {
		return [
			`worktree ${REPO_ROOT}`,
			"branch refs/heads/main",
			"",
			`worktree ${residueDir}`,
			"branch refs/heads/bt/residue",
			"",
		].join("\n");
	}

	let sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;
	const pi = {
		registerFlag() {},
		getFlag(name: string) {
			return flags[name];
		},
		on(event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) {
			if (event === "session_start") sessionStart = handler;
		},
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			if (argsEqual(args, ["rev-parse", "--show-toplevel"])) return ok(`${REPO_ROOT}\n`);
			if (argsEqual(args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				return ok(`${path.join(REPO_ROOT, ".git")}\n${path.join(REPO_ROOT, ".git")}\n`);
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "remote", "get-url", "origin"])) return ok(`${REMOTE_URL}\n`);
			if (argsEqual(args, ["-C", REPO_ROOT, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
				return ok("origin/main\n");
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "branch", "--show-current"])) return ok("main\n");
			if (argsEqual(args, ["-C", REPO_ROOT, "status", "--porcelain"])) return ok("");
			if (argsEqual(args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"])) return ok(listOutput());
			if (argsEqual(args, ["-C", residueDir, "status", "--porcelain"])) return ok(""); // clean
			if (args.includes("worktree") && args.includes("unlock")) {
				state.unlockCalls += 1;
				return ok("");
			}
			if (args.includes("worktree") && args.includes("remove")) {
				state.removeCalls += 1;
				state.removed = true;
				fsSync.rmSync(residueDir, { recursive: true, force: true });
				return ok("");
			}
			throw new Error(`Unexpected exec call: git ${JSON.stringify(args)}`);
		},
	} as unknown as ExtensionAPI;

	return {
		pi,
		state,
		sessionStart(event, ctx) {
			if (!sessionStart) throw new Error("session_start handler was not registered");
			return sessionStart(event, ctx);
		},
	};
}

function coldResidueDir(): string {
	// Modern nested label under the identity root, unlocked and clean: leaseless session
	// worktree, exactly what the cold backstop sweep reclaims.
	return path.join(worktreesRoot(), REPO_IDENTITY, "wt-nc", "residue");
}

describe("session_start --nc vs cold backstop sweep", () => {
	it("reaps cold clean residue at session start without the flag", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		const residueDir = path.join(worktreesRoot(), REPO_IDENTITY, "wt-nc", "residue");
		fsSync.mkdirSync(residueDir, { recursive: true });
		const notifications: string[] = [];
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(residueDir, { recursive: true, force: true });
		});

		const { pi, state, sessionStart } = sweepPi(residueDir, {});
		resetWorkspaceRuntimeForTesting();
		registerWorkspaceRuntime(pi);
		registerWorkspaceSession(pi);
		const ctx = createWorkspaceSessionContext("sess-sweep-control", notifications);

		await sessionStart({ type: "session_start", reason: "new" } as SessionStartEvent, ctx);

		assert.ok(
			notifications.includes("basecamp: reclaimed 1 cold worktree(s)"),
			`expected the sweep to reap the residue, got: ${JSON.stringify(notifications)}`,
		);
		assert.equal(state.removed, true, "the cold backstop sweep must reap leaseless clean residue");
		assert.equal(fsSync.existsSync(residueDir), false);
	});

	it("leaves the same residue in place when --nc is set", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		const residueDir = path.join(worktreesRoot(), REPO_IDENTITY, "wt-nc", "residue");
		fsSync.mkdirSync(residueDir, { recursive: true });
		const notifications: string[] = [];
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(residueDir, { recursive: true, force: true });
		});

		const { pi, state, sessionStart } = sweepPi(residueDir, { nc: true });
		resetWorkspaceRuntimeForTesting();
		registerWorkspaceRuntime(pi);
		registerWorkspaceSession(pi);
		const ctx = createWorkspaceSessionContext("sess-no-cleanup", notifications);

		await sessionStart({ type: "session_start", reason: "new" } as SessionStartEvent, ctx);

		assert.equal(state.removeCalls, 0, "--nc must skip the sweep entirely: no worktree remove");
		assert.equal(state.unlockCalls, 0, "--nc opts out before any worktree is touched");
		assert.ok(fsSync.existsSync(residueDir), "the dormant worktree must survive session start");
		assert.equal(
			notifications.some((n) => n.includes("reclaimed") || n.includes("dirty worktree")),
			false,
			`expected no sweep notifications, got: ${JSON.stringify(notifications)}`,
		);
	});
});
