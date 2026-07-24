import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../constants.ts";
import { SESSION_COLD_TTL_MS, sessionLeaseReason } from "../worktrees/lease.ts";
import { sweepSessionWorktrees } from "../worktrees/session-sweep.ts";
import { useTempWorktreesRoot } from "./worktree-root.ts";

useTempWorktreesRoot();

const IDENTITY = "org/repo";
const REPO_ROOT = "/repo";
const NOW = Date.parse("2026-07-23T12:00:00.000Z");

type ExecResult = { code: number; stdout: string; stderr: string };
interface WtSpec {
	label: string;
	branch: string | null;
	lockReason?: string | null;
	dirty?: boolean;
}

function wtPath(label: string): string {
	return path.join(worktreesRoot(), IDENTITY, label);
}

function listOutput(specs: WtSpec[]): string {
	const blocks = [`worktree ${REPO_ROOT}`, "branch refs/heads/main", ""];
	for (const spec of specs) {
		blocks.push(`worktree ${wtPath(spec.label)}`);
		blocks.push(spec.branch === null ? "detached" : `branch refs/heads/${spec.branch}`);
		if (spec.lockReason !== undefined && spec.lockReason !== null) blocks.push(`locked ${spec.lockReason}`);
		else if (spec.lockReason === null) blocks.push("locked");
		blocks.push("");
	}
	return blocks.join("\n");
}

function sweepPi(specs: WtSpec[]): { pi: ExtensionAPI; removed: string[] } {
	const removed: string[] = [];
	const dirtyByPath = new Map(specs.map((s) => [wtPath(s.label), s.dirty === true]));
	const pi = {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			if (args.includes("list")) return { code: 0, stdout: listOutput(specs), stderr: "" };
			if (args.includes("status")) {
				const dir = args[args.indexOf("-C") + 1] ?? "";
				return { code: 0, stdout: dirtyByPath.get(dir) ? " M f\n" : "", stderr: "" };
			}
			if (args.includes("remove")) {
				removed.push(args[args.length - 1] ?? "");
				return { code: 0, stdout: "", stderr: "" };
			}
			// unlock / lock and anything else succeed as no-ops
			return { code: 0, stdout: "", stderr: "" };
		},
	} as ExtensionAPI;
	return { pi, removed };
}

const stale = () => sessionLeaseReason("old", new Date(NOW - SESSION_COLD_TTL_MS - 1));
const fresh = () => sessionLeaseReason("live", new Date(NOW - 1000));

describe("sweepSessionWorktrees", () => {
	it("reclaims a cold+clean leased worktree and keeps its branch", async () => {
		const { pi, removed } = sweepPi([{ label: "wt-bt/feature", branch: "bt/feature", lockReason: stale() }]);
		const result = await sweepSessionWorktrees(pi, REPO_ROOT, IDENTITY, NOW);
		assert.deepEqual(result.reclaimed, [wtPath("wt-bt/feature")]);
		assert.deepEqual(removed, [wtPath("wt-bt/feature")]);
		assert.equal(result.surfaced.length, 0);
	});

	it("reclaims a leaseless (unlocked) legacy worktree when clean", async () => {
		const { pi, removed } = sweepPi([{ label: "copilot/slug", branch: "bt/slug", lockReason: undefined }]);
		const result = await sweepSessionWorktrees(pi, REPO_ROOT, IDENTITY, NOW);
		assert.deepEqual(result.reclaimed, [wtPath("copilot/slug")]);
		assert.deepEqual(removed, [wtPath("copilot/slug")]);
	});

	it("surfaces a cold+dirty worktree without removing it", async () => {
		const { pi, removed } = sweepPi([{ label: "wt-bt/wip", branch: "bt/wip", lockReason: stale(), dirty: true }]);
		const result = await sweepSessionWorktrees(pi, REPO_ROOT, IDENTITY, NOW);
		assert.deepEqual(result.surfaced, [wtPath("wt-bt/wip")]);
		assert.equal(result.reclaimed.length, 0);
		assert.equal(removed.length, 0);
	});

	it("skips a live (fresh-leased) worktree", async () => {
		const { pi, removed } = sweepPi([{ label: "wt-bt/active", branch: "bt/active", lockReason: fresh() }]);
		const result = await sweepSessionWorktrees(pi, REPO_ROOT, IDENTITY, NOW);
		assert.equal(result.kept, 1);
		assert.equal(result.reclaimed.length, 0);
		assert.equal(removed.length, 0);
	});

	it("never touches agent worktrees (daemon-owned)", async () => {
		const { pi, removed } = sweepPi([
			{ label: "agent-3f9a2c/worker", branch: "agent/brave-magpie", lockReason: "basecamp agent run old" },
			{ label: "agent-abc123/ask", branch: null },
		]);
		const result = await sweepSessionWorktrees(pi, REPO_ROOT, IDENTITY, NOW);
		assert.equal(removed.length, 0);
		assert.equal(result.reclaimed.length, 0);
	});
});
