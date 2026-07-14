import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { sweepAgentWorktrees } from "../worktrees/sweep.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

function porcelain(entries: Array<{ path: string; branch: string | null }>): string {
	return `${entries
		.map((e) => `worktree ${e.path}\n${e.branch ? `branch refs/heads/${e.branch}` : "detached"}`)
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
	});

	it("reaps nothing when there are no non-agent branches to merge into", async () => {
		const list = porcelain([{ path: "/wt/agent-x", branch: "agent-xxx/worker" }]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			throw new Error(`no merge-base/remove should run: ${args.join(" ")}`);
		});

		const result = await sweepAgentWorktrees(pi, "/repo");

		assert.deepEqual(result.removed, []);
		assert.equal(result.kept, 1);
	});
});
