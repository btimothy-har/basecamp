import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { assemblePrompt } from "../prompt.ts";

async function useTempHome(t: TestContext): Promise<string> {
	const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-prompts-"));
	const previousHome = process.env.HOME;
	process.env.HOME = homeDir;
	t.after(async () => {
		if (previousHome === undefined) {
			delete process.env.HOME;
		} else {
			process.env.HOME = previousHome;
		}
		await fs.rm(homeDir, { recursive: true, force: true });
	});
	return homeDir;
}

describe("assemblePrompt", () => {
	it("includes restored default engineering, mode, and environment prompts", async (t) => {
		await useTempHome(t);

		const prompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		assert.match(prompt, /# Direct Execution/);
		assert.match(prompt, /# Your Role as an Engineer/);
		assert.match(prompt, /You are a \*\*partner\*\*, not a follower\./);
		assert.match(prompt, /## Git CLI/);
		assert.match(prompt, /All git commands must go through `safe_git`\./);
	});

	it("uses user prompt and style overrides before built-ins", async (t) => {
		const homeDir = await useTempHome(t);
		const workspaceDir = path.join(homeDir, ".pi", "basecamp", "workspace");
		await fs.mkdir(path.join(workspaceDir, "prompts"), { recursive: true });
		await fs.mkdir(path.join(workspaceDir, "styles"), { recursive: true });
		await fs.writeFile(path.join(workspaceDir, "prompts", "environment.md"), "CUSTOM ENVIRONMENT PROMPT\n", "utf8");
		await fs.writeFile(path.join(workspaceDir, "styles", "engineering.md"), "CUSTOM ENGINEERING STYLE\n", "utf8");

		const prompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		assert.match(prompt, /CUSTOM ENGINEERING STYLE/);
		assert.match(prompt, /CUSTOM ENVIRONMENT PROMPT/);
		assert.doesNotMatch(prompt, /# Your Role as an Engineer/);
		assert.doesNotMatch(prompt, /## Git CLI/);
	});

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
