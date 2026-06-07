import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceState } from "../../platform/workspace.ts";
import { assemblePrompt } from "../prompt.ts";

describe("assemblePrompt", () => {
	it("includes unsafe-edit guidance when unsafe-edit is enabled without an active worktree", () => {
		const workspace: WorkspaceState = {
			launchCwd: "/repo",
			effectiveCwd: "/repo",
			scratchDir: "/tmp/pi/repo",
			repo: {
				isRepo: true,
				name: "repo",
				root: "/repo",
				remoteUrl: null,
			},
			protectedRoot: "/repo",
			activeWorktree: null,
			unsafeEdit: true,
		};

		const prompt = assemblePrompt({
			workspace,
			project: null,
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			agentPrompt: "custom agent prompt",
			readOnly: false,
		});

		assert.match(prompt, /⚠ UNSAFE-EDIT MODE ACTIVE:/);
		assert.match(prompt, /Parent file `edit`\/`write` calls may modify the protected checkout directly\./);
		assert.match(prompt, /Commits and mutating `safe_git` commands still require an active execution worktree\./);
		assert.match(prompt, /Subagents do not inherit unsafe-edit authority\./);
		assert.doesNotMatch(
			prompt,
			/⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory\. Do not edit the protected repository checkout\./,
		);
	});
});
