import assert from "node:assert/strict";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerWorkspaceRuntime, resetWorkspaceRuntimeForTesting } from "#core/project/workspace/runtime.ts";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";
import {
	selectWorktreeTarget,
	shouldReuseActiveWorktreeForHandoff,
	workspaceWorktreeToHandoffWorktree,
} from "../workflows/handoff/index.ts";

function worktree(overrides: Partial<WorkspaceWorktree> = {}): WorkspaceWorktree {
	return {
		kind: "git-worktree",
		label: "wt-bt/current-workstream",
		path: "/tmp/worktrees/wt-bt/current-workstream",
		branch: "bt/current-workstream",
		created: false,
		...overrides,
	};
}

interface EmittedEvent {
	channel: string;
	data: unknown;
}

class FakePi {
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};

	async exec(_command: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
		const invocation = args.join(" ");
		if (invocation === "rev-parse --show-toplevel") return { code: 0, stdout: "/repo\n", stderr: "" };
		if (invocation === "rev-parse --git-dir --git-common-dir") {
			return { code: 0, stdout: ".git\n.git\n", stderr: "" };
		}
		if (invocation === "-C /repo remote get-url origin") return { code: 1, stdout: "", stderr: "no remote" };
		if (invocation === "-C /repo worktree list --porcelain") {
			return { code: 0, stdout: "worktree /repo\nbranch refs/heads/main\n", stderr: "" };
		}
		throw new Error(`Unexpected git invocation: ${invocation}`);
	}
}

async function initializeWorkspace(t: TestContext, pi: FakePi): Promise<void> {
	resetWorkspaceRuntimeForTesting();
	t.after(resetWorkspaceRuntimeForTesting);
	const service = registerWorkspaceRuntime(pi as unknown as ExtensionAPI);
	await service.initialize({
		launchCwd: "/repo",
		unsafeEditFlag: false,
		unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
	});
}

function selectionContext(select: (choices: string[]) => Promise<string | undefined>): ExtensionContext {
	return {
		hasUI: true,
		sessionManager: { getSessionId: () => "session-1" },
		ui: {
			select: (_title: string, choices: string[]) => select(choices),
			input: async () => null,
			notify() {},
		},
	} as unknown as ExtensionContext;
}

const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for worktree selection" },
};
const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

describe("shouldReuseActiveWorktreeForHandoff", () => {
	it("reuses the active worktree only when it is a workstream (copilot/) worktree", () => {
		const workstreamWorktree = worktree({ label: "copilot/three-word-slug" });
		const planWorktree = worktree({ label: "wt-bt/current-workstream" });

		assert.equal(shouldReuseActiveWorktreeForHandoff(workstreamWorktree), true);
		assert.equal(shouldReuseActiveWorktreeForHandoff(planWorktree), false);
		assert.equal(shouldReuseActiveWorktreeForHandoff(null), false);
	});
});

describe("workspaceWorktreeToHandoffWorktree", () => {
	it("maps workspace worktrees to handoff worktrees", () => {
		assert.deepEqual(workspaceWorktreeToHandoffWorktree(worktree({ created: true })), {
			worktreeDir: "/tmp/worktrees/wt-bt/current-workstream",
			label: "wt-bt/current-workstream",
			branch: "bt/current-workstream",
			created: true,
		});
	});

	it("uses detached when the workspace worktree has no branch", () => {
		assert.deepEqual(workspaceWorktreeToHandoffWorktree(worktree({ branch: null })), {
			worktreeDir: "/tmp/worktrees/wt-bt/current-workstream",
			label: "wt-bt/current-workstream",
			branch: "detached",
			created: false,
		});
	});
});

describe("selectWorktreeTarget Herdr state", () => {
	it("marks Herdr blocked only while selecting a worktree", async (t) => {
		const pi = new FakePi();
		await initializeWorkspace(t, pi);
		const lifecycle: string[] = [];
		pi.events.emit = (channel, data) => {
			lifecycle.push(`${channel}:${(data as { active: boolean }).active}`);
			pi.emitted.push({ channel, data });
		};
		const ctx = selectionContext(async (choices) => {
			lifecycle.push("select");
			return choices[0];
		});

		const target = await selectWorktreeTarget(pi as unknown as ExtensionAPI, ctx, "Implement status", null);

		assert.ok(target);
		assert.deepEqual(lifecycle, ["herdr:blocked:true", "select", "herdr:blocked:false"]);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("clears blocked state when selection is cancelled or aborts", async (t) => {
		for (const selection of [
			async () => undefined,
			async () => {
				throw new DOMException("aborted", "AbortError");
			},
		]) {
			const pi = new FakePi();
			await initializeWorkspace(t, pi);
			try {
				await selectWorktreeTarget(
					pi as unknown as ExtensionAPI,
					selectionContext(selection),
					"Implement status",
					null,
				);
			} catch (error) {
				assert.equal((error as Error).name, "AbortError");
			}
			assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		}
	});

	it("does not report blocked state without an interactive UI", async () => {
		const pi = new FakePi();
		const result = await selectWorktreeTarget(
			pi as unknown as ExtensionAPI,
			{ hasUI: false } as ExtensionContext,
			"Implement status",
			null,
		);

		assert.equal(result, null);
		assert.deepEqual(pi.emitted, []);
	});
});
