import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { sweepAgentWorktrees } from "../worktrees/sweep.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

function porcelain(entries: Array<{ path: string; branch: string | null; locked?: boolean }>): string {
	return `${entries
		.map((entry) =>
			[
				`worktree ${entry.path}`,
				entry.branch ? `branch refs/heads/${entry.branch}` : "detached",
				...(entry.locked ? ["locked basecamp agent run"] : []),
			].join("\n"),
		)
		.join("\n\n")}\n\n`;
}

function execPi(handler: (args: string[]) => ExecResult, calls: string[][] = []): ExtensionAPI {
	return {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			calls.push(args);
			return handler(args);
		},
	} as ExtensionAPI;
}

describe("sweepAgentWorktrees", () => {
	it("reclaims agent worktrees whose branch is merged into a non-agent branch, keeps the rest", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/w0", branch: "wt-bt/feat" },
			{ path: "/wt/agent-merged", branch: "agent-aaa/worker" },
			{ path: "/wt/agent-open", branch: "agent-bbb/worker" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) {
				// agent-aaa is an ancestor of wt-bt/feat (merged); agent-bbb is merged nowhere.
				const merged = args.at(-2) === "agent-aaa/worker" && args.at(-1) === "wt-bt/feat";
				return { code: merged ? 0 : 1, stdout: "", stderr: "" };
			}
			return { code: 0, stdout: "", stderr: "" }; // unlock / remove / branch -D
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result.removed, ["/wt/agent-merged"]);
		assert.equal(result.kept, 1);
		assert.ok(
			calls.some((a) => a.includes("remove") && a.includes("/wt/agent-merged")),
			"removes the merged agent worktree",
		);
		assert.ok(
			calls.some((a) => a.includes("-D") && a.includes("agent-aaa/worker")),
			"deletes the merged branch",
		);
		assert.ok(
			!calls.some((a) => a.includes("remove") && a.includes("/wt/agent-open")),
			"leaves the unmerged agent worktree",
		);
		assert.equal(
			calls.some((args) => args.includes("--force")),
			false,
		);
		assert.equal(
			calls.some((args) => args.includes("unlock")),
			false,
		);
	});

	it("never inspects or removes a locked agent worktree", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-live", branch: "agent-live/worker", locked: true },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			throw new Error(`locked worktree should be untouched: ${args.join(" ")}`);
		});

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result, { removed: [], kept: 1 });
	});

	it("preserves a dirty merged worktree and its branch", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-dirty", branch: "agent-dirty/worker" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" };
			if (args.includes("remove")) return { code: 1, stdout: "", stderr: "worktree contains modified files" };
			return { code: 0, stdout: "", stderr: "" };
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result, { removed: [], kept: 1 });
		assert.ok(calls.some((args) => args.includes("remove") && args.includes("/wt/agent-dirty")));
		assert.equal(
			calls.some((args) => args.includes("--force") || args.includes("unlock")),
			false,
		);
		assert.equal(
			calls.some((args) => args.includes("-D") && args.includes("agent-dirty/worker")),
			false,
		);
	});

	it("reports a removed worktree even when branch cleanup fails", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-merged", branch: "agent-merged/worker" },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" };
			if (args.includes("-D")) return { code: 1, stdout: "", stderr: "branch cleanup failed" };
			return { code: 0, stdout: "", stderr: "" };
		});

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result, { removed: ["/wt/agent-merged"], kept: 0 });
	});

	it("reaps nothing when there are no non-agent branches to merge into", async () => {
		const list = porcelain([{ path: "/wt/agent-x", branch: "agent-xxx/worker" }]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("log")) return { code: 0, stdout: "real work\n", stderr: "" };
			throw new Error(`no merge-base/remove should run: ${args.join(" ")}`);
		});

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result.removed, []);
		assert.equal(result.kept, 1);
	});

	it("recognizes per-agent `agent/<handle>` branches alongside legacy `agent-` ones", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-new", branch: "agent/quiet-badger-3dc450" },
			{ path: "/wt/agent-old", branch: "agent-aaa/worker" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" };
			return { code: 0, stdout: "", stderr: "" };
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result.removed.sort(), ["/wt/agent-new", "/wt/agent-old"]);
		assert.ok(calls.some((args) => args.includes("-D") && args.includes("agent/quiet-badger-3dc450")));
	});

	it("reaps a snapshot-only branch (run committed nothing) even when unmerged", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-snap", branch: "agent/idle-fox-0a1b2c" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("log")) return { code: 0, stdout: "basecamp dispatch snapshot\n", stderr: "" };
			if (args.includes("merge-base")) throw new Error("snapshot-only short-circuits the merge probe");
			return { code: 0, stdout: "", stderr: "" };
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result.removed, ["/wt/agent-snap"]);
		assert.ok(calls.some((args) => args.includes("-D") && args.includes("agent/idle-fox-0a1b2c")));
	});

	it("keeps an unmerged branch with real commits", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-work", branch: "agent/busy-elk-9f8e7d" },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("log")) return { code: 0, stdout: "implement the fix\n", stderr: "" };
			if (args.includes("merge-base")) return { code: 1, stdout: "", stderr: "" };
			throw new Error(`unmerged real work must not be removed: ${args.join(" ")}`);
		});

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result, { removed: [], kept: 1 });
	});
});
