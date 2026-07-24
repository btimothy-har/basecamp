import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { useTempWorktreesRoot } from "../../../git/tests/worktree-root.ts";
import { parseSessionLease } from "../../../git/worktrees/lease.ts";
import { WorkspaceRuntimeService } from "../runtime.ts";
import { createLinkedWorktreePi, type ExecCall, REPO_ROOT, WORKTREE_DIR } from "./service-harness.ts";

useTempWorktreesRoot();

const CONSTRAINTS = { readOnly: false, hasUI: true, isSubagent: false, sandboxed: false };

/**
 * Wrap the linked-worktree discovery mock so it also accepts (and records) lock/unlock,
 * optionally presenting the worktree as already locked with `lockReason`.
 */
function leaseAwarePi(lockReason?: string): { pi: ExtensionAPI; calls: ExecCall[] } {
	const { pi: base, calls } = createLinkedWorktreePi({ toplevel: WORKTREE_DIR, branch: "wt/feature" });
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }) {
			if (command === "git" && (args.includes("lock") || args.includes("unlock"))) {
				calls.push({ command, args, options });
				return { code: 0, stdout: "", stderr: "" };
			}
			if (command === "git" && args.includes("list") && lockReason !== undefined) {
				calls.push({ command, args, options });
				const listOut = `worktree ${REPO_ROOT}\nbranch refs/heads/main\n\nworktree ${WORKTREE_DIR}\nbranch refs/heads/wt/feature\nlocked ${lockReason}\n\n`;
				return { code: 0, stdout: listOut, stderr: "" };
			}
			return base.exec(command, args, options);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

function findLockCall(calls: ExecCall[]): ExecCall | undefined {
	return calls.find((c) => c.args.includes("lock") && c.args.includes("--reason"));
}

describe("session-worktree leasing on adoption", () => {
	it("leases the adopted linked worktree with the session id", async () => {
		const { pi, calls } = leaseAwarePi();
		const service = new WorkspaceRuntimeService(pi);

		await service.initialize({
			launchCwd: WORKTREE_DIR,
			sessionId: "sess-xyz",
			unsafeEditFlag: false,
			unsafeEditConstraints: CONSTRAINTS,
		});

		const lock = findLockCall(calls);
		assert.ok(lock, "expected a worktree lock (lease) to be issued");
		const reason = lock.args[lock.args.indexOf("--reason") + 1];
		assert.equal(parseSessionLease(reason)?.sessionId, "sess-xyz");
		assert.equal(lock.args[lock.args.length - 1], WORKTREE_DIR);
	});

	it("does not lease when there is no session id (subagent)", async () => {
		const { pi, calls } = leaseAwarePi();
		const service = new WorkspaceRuntimeService(pi);

		await service.initialize({
			launchCwd: WORKTREE_DIR,
			sessionId: null,
			unsafeEditFlag: false,
			unsafeEditConstraints: CONSTRAINTS,
		});

		assert.equal(findLockCall(calls), undefined, "a subagent must not clobber the agent lock with a session lease");
	});

	it("does not clobber an agent lock when a top-level session adopts an agent worktree", async () => {
		const { pi, calls } = leaseAwarePi("basecamp agent run 2026-07-23T09:00:00.000Z");
		const service = new WorkspaceRuntimeService(pi);

		await service.initialize({
			launchCwd: WORKTREE_DIR,
			sessionId: "sess-human",
			unsafeEditFlag: false,
			unsafeEditConstraints: CONSTRAINTS,
		});

		assert.equal(service.current()?.activeWorktree?.path, WORKTREE_DIR, "the worktree is still adopted");
		assert.equal(
			findLockCall(calls),
			undefined,
			"a session lease must never overwrite the daemon's agent-run lock — that would orphan the worktree from both owners' teardown",
		);
		assert.ok(!calls.some((c) => c.args.includes("unlock")), "the agent lock must not even be transiently unlocked");
	});

	it("still leases an adopted worktree whose lease belongs to an earlier session", async () => {
		const { pi, calls } = leaseAwarePi("basecamp session sess-old 2026-07-23T09:00:00.000Z");
		const service = new WorkspaceRuntimeService(pi);

		await service.initialize({
			launchCwd: WORKTREE_DIR,
			sessionId: "sess-new",
			unsafeEditFlag: false,
			unsafeEditConstraints: CONSTRAINTS,
		});

		const lock = findLockCall(calls);
		assert.ok(lock, "an old session lease is taken over, not treated as foreign");
		assert.equal(parseSessionLease(lock.args[lock.args.indexOf("--reason") + 1])?.sessionId, "sess-new");
	});
});
