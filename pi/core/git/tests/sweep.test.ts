import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../constants.ts";
import { sweepAgentWorktrees } from "../worktrees/sweep.ts";
import { useTempWorktreesRoot } from "./worktree-root.ts";

useTempWorktreesRoot();

const DETACHED = (token: string, name: string) => path.join(worktreesRoot(), "o", "r", `agent-${token}`, name);

type ExecResult = { code: number; stdout: string; stderr: string };

const FRESH_LOCK = `basecamp agent run ${new Date().toISOString()}`;
const STALE_LOCK = `basecamp agent run ${new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString()}`;

function porcelain(entries: Array<{ path: string; branch: string | null; lockReason?: string }>): string {
	return `${entries
		.map((entry) =>
			[
				`worktree ${entry.path}`,
				entry.branch ? `branch refs/heads/${entry.branch}` : "detached",
				...(entry.lockReason ? [`locked ${entry.lockReason}`] : []),
			].join("\n"),
		)
		.join("\n\n")}\n\n`;
}

function execPi(handler: (args: string[]) => ExecResult | null, calls: string[][] = []): ExtensionAPI {
	return {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			calls.push(args);
			const result = handler(args);
			if (result) return result;
			if (args.includes("--format=%(refname:short)")) return { code: 0, stdout: "main\n", stderr: "" };
			return { code: 0, stdout: "", stderr: "" };
		},
	} as unknown as ExtensionAPI;
}

describe("sweepAgentWorktrees", () => {
	it("reclaims unlocked agent worktrees with integrated branches, keeps outstanding work", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/w0", branch: "wt-bt/feat" },
			{ path: "/wt/agent-merged", branch: "agent/idle-fox-0a1b2c" },
			{ path: "/wt/agent-open", branch: "agent-bbb/worker" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) {
				const merged = args.at(-2) === "agent/idle-fox-0a1b2c" && args.at(-1) === "wt-bt/feat";
				return { code: merged ? 0 : 1, stdout: "", stderr: "" };
			}
			return null;
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");

		assert.deepEqual(result.removed, ["/wt/agent-merged"]);
		assert.equal(result.kept, 1);
		assert.ok(calls.some((a) => a.includes("-D") && a.includes("agent/idle-fox-0a1b2c")));
		assert.ok(
			!calls.some((a) => a.includes("remove") && a.includes("/wt/agent-open")),
			"unintegrated real work survives",
		);
	});

	it("reclaims an unlocked detached agent workspace (report/ask residue)", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: DETACHED("abc123", "ask"), branch: null },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => (args.includes("list") ? { code: 0, stdout: list, stderr: "" } : null), calls);

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");

		assert.deepEqual(result.removed, [DETACHED("abc123", "ask")]);
		assert.equal(
			calls.some((a) => a.includes("-D")),
			false,
			"detached residue has no branch to delete",
		);
	});

	it("reclaims detached residue for a single-segment repo identity (no origin remote)", async () => {
		// deriveRepoIdentity falls back to a bare basename when there is no parseable remote, so
		// the workspace path is <root>/<repo>/agent-<token>/<name> — 3 segments, not 4.
		const detached = path.join(worktreesRoot(), "localrepo", "agent-xyz789", "ask");
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: detached, branch: null },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => (args.includes("list") ? { code: 0, stdout: list, stderr: "" } : null), calls);

		const result = await sweepAgentWorktrees(pi, "/repo", "localrepo");

		assert.deepEqual(result.removed, [detached], "single-segment-identity residue is reclaimed");
	});

	it("never claims bare human agent-* branches or lookalike paths", async () => {
		const calls: string[][] = [];
		const worktrees = porcelain([
			{ path: "/repo", branch: "main" },
			// Human branch that merely shares the legacy prefix — integrated, but not agent residue.
			{ path: "/wt/dash", branch: "agent-dashboard" },
			// Detached worktree of a repo literally named agent-tools — label depth doesn't match.
			{ path: path.join(worktreesRoot(), "o", "agent-tools", "bisect"), branch: null },
			// Detached worktree outside Basecamp's root entirely.
			{ path: "/build/agent-abc123/checkout", branch: null },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: worktrees, stderr: "" };
			if (args.includes("--format=%(refname:short)"))
				return { code: 0, stdout: "main\nagent-dashboard\nagent-experiments\n", stderr: "" };
			if (args.includes("--is-ancestor")) return { code: 0, stdout: "", stderr: "" };
			return null;
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");

		assert.deepEqual(result.removed, []);
		assert.equal(
			calls.some((a) => a.includes("remove") || a.includes("-D")),
			false,
			"nothing is removed and no branch is deleted",
		);
	});

	it("never touches a freshly locked live workspace", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-live", branch: "agent/busy-elk-9f8e7d", lockReason: FRESH_LOCK },
			{ path: DETACHED("def456", "ask"), branch: null, lockReason: FRESH_LOCK },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" }; // even integrated
			if (args.includes("remove") || args.includes("unlock")) throw new Error("live workspace touched");
			return null;
		});

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");
		assert.deepEqual(result.removed, []);
	});

	it("breaks a provably stale agent lock and reclaims integrated/detached residue", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-stale", branch: "agent/gone-owl-112233", lockReason: STALE_LOCK },
			{ path: DETACHED("ghi789", "ask"), branch: null, lockReason: STALE_LOCK },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" }; // integrated
			return null;
		}, calls);

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");

		assert.deepEqual(result.removed.sort(), [DETACHED("ghi789", "ask"), "/wt/agent-stale"]);
		const unlockIdx = calls.findIndex((a) => a.includes("unlock"));
		const removeIdx = calls.findIndex((a) => a.includes("remove"));
		assert.ok(unlockIdx !== -1 && unlockIdx < removeIdx, "unlocks before removing");
	});

	it("keeps a stale-locked workspace whose branch has unintegrated commits", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-wip", branch: "agent/late-bee-445566", lockReason: STALE_LOCK },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 1, stdout: "", stderr: "" }; // unmerged
			if (args.includes("remove")) throw new Error("unintegrated work must survive");
			return null;
		});

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");
		assert.deepEqual(result.removed, []);
		assert.equal(result.kept, 1);
	});

	it("skips locked workspaces with untimestamped legacy lock reasons", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/agent-legacy", branch: "agent-aaa/worker", lockReason: "basecamp agent run" },
		]);
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("merge-base")) return { code: 0, stdout: "", stderr: "" };
			if (args.includes("remove")) throw new Error("cannot age-gate without a timestamp");
			return null;
		});

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");
		assert.deepEqual(result.removed, []);
	});

	it("deletes integrated orphan agent branches with no worktree, keeps unintegrated ones", async () => {
		const list = porcelain([
			{ path: "/repo", branch: "main" },
			{ path: "/wt/w0", branch: "wt-bt/feat" },
		]);
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: list, stderr: "" };
			if (args.includes("--format=%(refname:short)")) {
				return { code: 0, stdout: "main\nwt-bt/feat\nagent/orphan-merged-1\nagent/orphan-open-2\n", stderr: "" };
			}
			if (args.includes("merge-base")) {
				const merged = args.at(-2) === "agent/orphan-merged-1";
				return { code: merged ? 0 : 1, stdout: "", stderr: "" };
			}
			return null;
		}, calls);

		await sweepAgentWorktrees(pi, "/repo", "o/r");

		assert.ok(calls.some((a) => a.includes("-D") && a.includes("agent/orphan-merged-1")));
		assert.equal(
			calls.some((a) => a.includes("-D") && a.includes("agent/orphan-open-2")),
			false,
			"unintegrated orphan branches are kept",
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
			return null;
		});

		const result = await sweepAgentWorktrees(pi, "/repo", "o/r");
		assert.deepEqual(result.removed, ["/wt/agent-merged"]);
	});
});
