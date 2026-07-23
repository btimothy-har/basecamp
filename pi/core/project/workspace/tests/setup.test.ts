import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runWorktreeSetup } from "../setup.ts";

interface ExecOptions {
	cwd?: string;
	timeout?: number;
}

interface ExecResult {
	stdout: string;
	stderr: string;
	code: number;
	killed: boolean;
}

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

function createPi(result: ExecResult, onExec?: () => void): { pi: ExtensionAPI; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: ExecOptions): Promise<ExecResult> {
			calls.push({ command, args, options });
			onExec?.();
			return result;
		},
	} as ExtensionAPI;
	return { pi, calls };
}

describe("runWorktreeSetup", () => {
	it("runs the hook via env(1) with the default timeout and returns success", async () => {
		const command = "uv sync";
		const worktreeDir = "/worktree";
		const repoRoot = "/repo";
		const { pi, calls } = createPi({ code: 0, stdout: "", stderr: "", killed: false });

		const result = await runWorktreeSetup(pi, { command, worktreeDir, repoRoot });

		assert.deepEqual(result, { ran: true, exitCode: 0, timedOut: false, stderrTail: "" });
		assert.equal(calls.length, 1);
		assert.equal(calls[0]?.command, "env");
		// BASECAMP_REPO_ROOT rides on the hook's own environment — never a process.env mutation,
		// which would race concurrent dispatch provisioning.
		assert.deepEqual(calls[0]?.args, [`BASECAMP_REPO_ROOT=${repoRoot}`, "bash", "-lc", command]);
		assert.equal(calls[0]?.options?.cwd, worktreeDir);
		assert.equal(calls[0]?.options?.timeout, 180_000);
	});

	it("returns non-zero exits without throwing", async () => {
		const { pi } = createPi({ code: 2, stdout: "", stderr: "boom", killed: false });

		const result = await runWorktreeSetup(pi, {
			command: "false",
			worktreeDir: "/worktree",
			repoRoot: "/repo",
		});

		assert.deepEqual(result, { ran: true, exitCode: 2, timedOut: false, stderrTail: "boom" });
	});

	it("reports timeouts from killed exec results", async () => {
		const { pi } = createPi({ code: 143, stdout: "", stderr: "timed out", killed: true });

		const result = await runWorktreeSetup(pi, {
			command: "sleep 999",
			worktreeDir: "/worktree",
			repoRoot: "/repo",
		});

		assert.equal(result.timedOut, true);
		assert.equal(result.exitCode, 143);
		assert.equal(result.stderrTail, "timed out");
	});

	it("never mutates the extension process environment", async () => {
		const prev = process.env.BASECAMP_REPO_ROOT;
		delete process.env.BASECAMP_REPO_ROOT;
		try {
			const { pi } = createPi({ code: 0, stdout: "", stderr: "", killed: false }, () => {
				assert.equal(process.env.BASECAMP_REPO_ROOT, undefined, "no global mutation during exec");
			});

			await runWorktreeSetup(pi, { command: "true", worktreeDir: "/worktree", repoRoot: "/repo" });

			assert.equal(process.env.BASECAMP_REPO_ROOT, undefined);
		} finally {
			if (prev !== undefined) process.env.BASECAMP_REPO_ROOT = prev;
		}
	});

	it("forwards a custom timeout", async () => {
		const { pi, calls } = createPi({ code: 0, stdout: "", stderr: "", killed: false });

		await runWorktreeSetup(pi, {
			command: "true",
			worktreeDir: "/worktree",
			repoRoot: "/repo",
			timeoutMs: 5000,
		});

		assert.equal(calls[0]?.options?.timeout, 5000);
	});
});
