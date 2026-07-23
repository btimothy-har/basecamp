import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { useTempWorktreesRoot } from "../../../git/tests/worktree-root.ts";
import { parseSessionLease } from "../../../git/worktrees/lease.ts";
import { WorkspaceRuntimeService } from "../runtime.ts";
import { createLinkedWorktreePi, type ExecCall, WORKTREE_DIR } from "./service-harness.ts";

useTempWorktreesRoot();

const CONSTRAINTS = { readOnly: false, hasUI: true, isSubagent: false, sandboxed: false };

/** Wrap the linked-worktree discovery mock so it also accepts (and records) lock/unlock. */
function leaseAwarePi(): { pi: ExtensionAPI; calls: ExecCall[] } {
	const { pi: base, calls } = createLinkedWorktreePi({ toplevel: WORKTREE_DIR, branch: "wt/feature" });
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }) {
			if (command === "git" && (args.includes("lock") || args.includes("unlock"))) {
				calls.push({ command, args, options });
				return { code: 0, stdout: "", stderr: "" };
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
});
