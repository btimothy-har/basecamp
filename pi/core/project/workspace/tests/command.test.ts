import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { useTempWorktreesRoot } from "../../../git/tests/worktree-root.ts";
import { CREATE_CHOICE, createWorktreeFlow, promptWorktreeChoice, type WorktreeSelection } from "../command.ts";
import type { WorkspaceRuntimeService } from "../runtime.ts";
import type { RepoContext, WorkspaceWorktree } from "../state.ts";

// Deterministic user prefix so branch assertions don't depend on the runner's $USER.
process.env.USER = "zz";
useTempWorktreesRoot();

type ExecResult = { code: number; stdout: string; stderr: string };
type WorktreeSummary = { label: string; path: string; branch: string };

function summary(label: string): WorktreeSummary {
	return { label, path: `/tmp/worktrees/${label}`, branch: `wt/${label}` };
}

function ctxWith(opts: {
	select?: (choices: string[]) => Promise<string | undefined>;
	input?: () => Promise<string | null>;
	sessionId?: string;
}): ExtensionContext {
	return {
		hasUI: true,
		sessionManager: { getSessionId: () => opts.sessionId ?? "0000" },
		ui: {
			select: (_title: string, choices: string[]) => (opts.select ?? (async () => undefined))(choices),
			input: opts.input ?? (async () => null),
			notify() {},
		},
	} as unknown as ExtensionContext;
}

describe("promptWorktreeChoice", () => {
	it("offers Create new first, then existing worktrees", async () => {
		let offered: string[] = [];
		const ctx = ctxWith({
			select: async (choices) => {
				offered = choices;
				return choices[0];
			},
		});

		const result = await promptWorktreeChoice(ctx, [summary("foo")], null);

		assert.equal(offered[0], CREATE_CHOICE);
		assert.equal(offered.length, 2);
		assert.deepEqual(result, { kind: "create" } satisfies WorktreeSelection);
	});

	it("maps a selected existing worktree to a switch", async () => {
		const ctx = ctxWith({ select: async (choices) => choices[1] });

		const result = await promptWorktreeChoice(ctx, [summary("foo")], null);

		assert.deepEqual(result, { kind: "switch", label: "foo" } satisfies WorktreeSelection);
	});

	it("returns null without an interactive UI", async () => {
		const result = await promptWorktreeChoice({ hasUI: false } as ExtensionContext, [summary("foo")], null);
		assert.equal(result, null);
	});
});

describe("createWorktreeFlow", () => {
	const repo: RepoContext = { isRepo: true, name: "org/repo", root: "/repo", remoteUrl: null };

	function listPi(): ExtensionAPI {
		return {
			async exec(command: string, args: string[]): Promise<ExecResult> {
				if (command === "git" && args.join(" ") === "-C /repo worktree list --porcelain") {
					return { code: 0, stdout: "worktree /repo\nbranch refs/heads/main\n\n", stderr: "" };
				}
				return { code: 0, stdout: "", stderr: "" };
			},
		} as unknown as ExtensionAPI;
	}

	function stubWorkspace(): {
		workspace: WorkspaceRuntimeService;
		activated: () => { label: string; branch: string | null } | null;
	} {
		let activated: { label: string; branch: string | null } | null = null;
		const workspace = {
			activateWorktree: async (label: string, branch?: string | null): Promise<WorkspaceWorktree> => {
				activated = { label, branch: branch ?? null };
				return { kind: "git-worktree", label, path: `/wt/${label}`, branch: branch ?? null, created: true };
			},
		} as unknown as WorkspaceRuntimeService;
		return { workspace, activated: () => activated };
	}

	it("provisions a generic wt/<slug> worktree on a unique branch from the typed slug", async () => {
		const { workspace, activated } = stubWorkspace();
		const ctx = ctxWith({ input: async () => "Add caching", sessionId: "0000" });

		await createWorktreeFlow(listPi(), ctx, workspace, repo);

		assert.deepEqual(activated(), { label: "wt/add-caching", branch: "zz/0000-add-caching" });
	});

	it("does not activate anything when the slug prompt is cancelled", async () => {
		const { workspace, activated } = stubWorkspace();
		const ctx = ctxWith({ input: async () => "   " });

		await createWorktreeFlow(listPi(), ctx, workspace, repo);

		assert.equal(activated(), null);
	});
});
