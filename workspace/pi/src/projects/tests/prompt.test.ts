import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { resetAgentMode, setAgentMode } from "pi-core/session/agent-mode.ts";
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

function useDefaultAgentMode(t: TestContext): void {
	resetAgentMode();
	t.after(() => {
		resetAgentMode();
	});
}

function useAgentMode(t: TestContext, mode: Parameters<typeof setAgentMode>[0]): void {
	useDefaultAgentMode(t);
	setAgentMode(mode);
}

describe("assemblePrompt", () => {
	it("includes restored default engineering, mode, and environment prompts", async (t) => {
		useDefaultAgentMode(t);
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
		assert.match(prompt, /## Git & GitHub/);
		assert.match(prompt, /Use `git` and `gh` directly in bash like a normal developer\./);
	});

	it("uses user prompt and style overrides before built-ins", async (t) => {
		useDefaultAgentMode(t);
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
		assert.doesNotMatch(prompt, /## Git & GitHub/);
	});

	it("includes unsafe-edit guidance when unsafe-edit is enabled without an active worktree", (t) => {
		useDefaultAgentMode(t);
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
		assert.match(prompt, /Commits and mutating git commands still require an active execution worktree\./);
		assert.match(prompt, /Subagents do not inherit unsafe-edit authority\./);
		assert.doesNotMatch(
			prompt,
			/⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory\. Do not edit the protected repository checkout\./,
		);
	});

	it("includes copilot mode and Repo Logseq without engineering style", async (t) => {
		useAgentMode(t, "copilot");
		const homeDir = await useTempHome(t);
		const workspaceDir = path.join(homeDir, ".pi", "basecamp", "workspace");
		await fs.mkdir(path.join(workspaceDir, "styles"), { recursive: true });
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

		assert.match(prompt, /# Repo Copilot/);
		assert.match(prompt, /# Repo Logseq/);
		assert.doesNotMatch(prompt, /# Repo Copilot Context/);
		assert.doesNotMatch(prompt, /# Your Role as an Engineer/);
		assert.doesNotMatch(prompt, /CUSTOM ENGINEERING STYLE/);
	});

	it("copilot mode documents workstream launch, dedupe, pull-based curation, and the plan() sibling", async (t) => {
		useAgentMode(t, "copilot");
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

		// staged handoff: launch_workstream stages a pane + id; user starts pi with --workstream
		assert.match(prompt, /launch_workstream/);
		assert.match(prompt, /list_workstream_launches/);
		assert.match(prompt, /It does not start an agent/);
		assert.match(prompt, /Tell the user to run `pi --workstream` in the opened pane/);
		assert.match(prompt, /infers the id from the worktree/);
		assert.match(prompt, /`cd <worktree-path> && pi --workstream`/);
		// launch_workstream and plan() are siblings, plan() stays the in-session handoff
		assert.match(prompt, /siblings, not replacements/);
		assert.match(prompt, /in-session implementation handoff/);
		// non-management framing: copilot does not drive the workstream session
		assert.match(prompt, /do not supervise, drive, or manage it/);
		// pull-based curation (handle only after pi --workstream) and no-Logseq-write rule preserved
		assert.match(prompt, /ask_agent/);
		assert.match(prompt, /Workstream agents never write Logseq/);
		// launch index is an operational receipt, not durable workstream status
		assert.match(prompt, /operational receipt[\s\S]*not workstream status/);
	});

	it("places Repo Logseq after project context and before the environment block", async (t) => {
		useAgentMode(t, "copilot");
		await useTempHome(t);

		const prompt = assemblePrompt({
			workspace: null,
			project: {
				projectName: "test-project",
				project: null,
				additionalDirs: [],
				workingStyle: "engineering",
				contextContent: "Project-specific context.",
				warnings: [],
			},
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		const projectContextIndex = prompt.indexOf("# Project Context");
		const logseqContextIndex = prompt.indexOf("# Repo Logseq");
		const envBlockIndex = prompt.indexOf("You are an AI assistant. You are operating inside pi-coding-agent");

		assert.notEqual(projectContextIndex, -1);
		assert.notEqual(logseqContextIndex, -1);
		assert.notEqual(envBlockIndex, -1);
		assert.ok(projectContextIndex < logseqContextIndex);
		assert.ok(logseqContextIndex < envBlockIndex);
	});

	it("does not include Repo Logseq for agent prompts in copilot mode", async (t) => {
		useAgentMode(t, "copilot");
		await useTempHome(t);

		const prompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			agentPrompt: "custom worker prompt",
			readOnly: false,
		});

		assert.match(prompt, /custom worker prompt/);
		assert.doesNotMatch(prompt, /# Repo Copilot/);
		assert.doesNotMatch(prompt, /# Repo Logseq/);
	});
});
