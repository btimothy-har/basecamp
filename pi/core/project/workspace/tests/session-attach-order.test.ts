import assert from "node:assert/strict";
import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../../../git/constants.ts";
import { parseSessionLease } from "../../../git/worktrees/lease.ts";
import { registerWorkspaceRuntime, resetWorkspaceRuntimeForTesting } from "../runtime.ts";
import { registerWorkspaceSession } from "../session.ts";
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

interface LeaseState {
	lockReason: string | null;
	removed: boolean;
}

/**
 * Stateful git mock for the session_start ordering test: lock/unlock/remove mutate `state`,
 * and later `worktree list` calls reflect it — so the cold backstop sweep sees exactly the
 * lease the attach did (or did not) take, as real git would. `remove` deletes the real
 * directory, making a sweep-before-attach ordering bug observable as a failed attach.
 */
function statefulSessionPi(
	targetDir: string,
	targetBranch: string,
): {
	pi: ExtensionAPI;
	state: LeaseState;
	sessionStart: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>;
} {
	const state: LeaseState = { lockReason: null, removed: false };

	function listOutput(): string {
		const blocks = [`worktree ${REPO_ROOT}`, "branch refs/heads/main", ""];
		if (!state.removed) {
			blocks.push(`worktree ${targetDir}`, `branch refs/heads/${targetBranch}`);
			if (state.lockReason !== null) blocks.push(`locked ${state.lockReason}`);
			blocks.push("");
		}
		return blocks.join("\n");
	}

	let sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;
	const pi = {
		registerFlag() {},
		getFlag(name: string) {
			return name === "worktree-dir" ? targetDir : undefined;
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
			if (argsEqual(args, ["-C", targetDir, "status", "--porcelain"])) return ok(""); // clean
			if (args.includes("worktree") && args.includes("unlock")) {
				state.lockReason = null;
				return ok("");
			}
			if (args.includes("worktree") && args.includes("lock")) {
				state.lockReason = args[args.indexOf("--reason") + 1] ?? null;
				return ok("");
			}
			if (args.includes("worktree") && args.includes("remove")) {
				state.removed = true;
				fsSync.rmSync(targetDir, { recursive: true, force: true });
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

describe("session_start --worktree-dir attach vs cold backstop sweep ordering", () => {
	it("attaches (and leases) an unlocked cold-but-clean target instead of sweeping it away", async (t) => {
		const envSnapshot = snapshotWorkspaceEnv();
		clearAgentDepthEnv();
		// Pre-lease-era residue: registered with git, clean, and unlocked — exactly what the
		// cold backstop would reap. Pointing --worktree-dir at it must attach, not destroy.
		const targetDir = path.join(worktreesRoot(), REPO_IDENTITY, "wt-bt", "target");
		fsSync.mkdirSync(targetDir, { recursive: true });
		const notifications: string[] = [];
		t.after(async () => {
			restoreWorkspaceEnv(envSnapshot);
			await fs.rm(SCRATCH_DIR, { recursive: true, force: true });
			await fs.rm(targetDir, { recursive: true, force: true });
		});

		const { pi, state, sessionStart } = statefulSessionPi(targetDir, "bt/target");
		resetWorkspaceRuntimeForTesting();
		const service = registerWorkspaceRuntime(pi);
		registerWorkspaceSession(pi);
		const ctx = createWorkspaceSessionContext("sess-attach-order", notifications);

		await sessionStart({ type: "session_start", reason: "resume" } as SessionStartEvent, ctx);

		assert.ok(
			notifications.includes("basecamp: worktree attached → wt-bt/target"),
			`expected a successful attach, got: ${JSON.stringify(notifications)}`,
		);
		assert.equal(state.removed, false, "the sweep must not reap the --worktree-dir target");
		assert.ok(fsSync.existsSync(targetDir), "the target directory must survive session start");
		assert.equal(service.current()?.activeWorktree?.path, targetDir);
		assert.equal(
			parseSessionLease(state.lockReason)?.sessionId,
			"sess-attach-order",
			"the attach leases the target, which is what shields it from the sweep",
		);
	});
});
