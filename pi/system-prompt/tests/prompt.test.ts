import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import { resetAgentMode, setAgentMode } from "#core/agent-mode/index.ts";
import type { CatalogItem } from "#core/catalog/index.ts";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
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

		assert.match(prompt, /# Work/);
		assert.match(prompt, /# Your Role as an Engineer/);
		assert.match(prompt, /You are a \*\*partner\*\*, not a follower\./);
		assert.match(prompt, /## Git & GitHub/);
		assert.match(prompt, /Use `git` and `gh` directly in bash like a normal developer\./);
	});

	it("uses user prompt and style overrides before built-ins", async (t) => {
		useDefaultAgentMode(t);
		const homeDir = await useTempHome(t);
		const basecampDir = path.join(homeDir, ".pi", "basecamp");
		await fs.mkdir(path.join(basecampDir, "prompts"), { recursive: true });
		await fs.mkdir(path.join(basecampDir, "styles"), { recursive: true });
		await fs.writeFile(path.join(basecampDir, "prompts", "environment.md"), "CUSTOM ENVIRONMENT PROMPT\n", "utf8");
		await fs.writeFile(path.join(basecampDir, "styles", "engineering.md"), "CUSTOM ENGINEERING STYLE\n", "utf8");

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
		const basecampDir = path.join(homeDir, ".pi", "basecamp");
		await fs.mkdir(path.join(basecampDir, "styles"), { recursive: true });
		await fs.writeFile(path.join(basecampDir, "styles", "engineering.md"), "CUSTOM ENGINEERING STYLE\n", "utf8");

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

	it("copilot mode documents workstream launch, dedupe, and pull-based curation", async (t) => {
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

		// decoupled surface: create/edit shape the record; launch stages the worktree + pane
		assert.match(prompt, /create_workstream/);
		assert.match(prompt, /edit_workstream/);
		assert.match(prompt, /launch_workstream/);
		assert.match(prompt, /list_workstreams/);
		assert.match(prompt, /set_workstream_status/);
		// the migrated tool name replaces the deprecated launch-index name
		assert.doesNotMatch(prompt, /list_workstream_launches/);
		// content versioning: edit revises in place and retains the prior version
		assert.match(prompt, /keeps the old version/);
		assert.match(prompt, /It does not start an agent/);
		assert.match(prompt, /Tell the user to run `pi --workstream` in the opened pane/);
		assert.match(prompt, /infers the slug from the worktree label/);
		assert.match(prompt, /`cd <worktree-path> && pi --workstream=<slug>`/);
		// launch is decoupled from the record, so the same workstream carries across repos
		assert.match(prompt, /launched into a different repo for cross-repo coordination/);
		// --copilot dropped the plan() sibling framing; copilot stages but does not implement in-session
		assert.doesNotMatch(prompt, /plan\(\)/);
		assert.doesNotMatch(prompt, /siblings, not replacements/);
		assert.match(prompt, /Copilot stages work; it does not implement in-session/);
		// non-management framing: copilot does not drive the workstream session
		assert.match(prompt, /do not supervise, drive, or manage it/);
		// pull-based curation (handle only after pi --workstream) and no-Logseq-write rule preserved
		assert.match(prompt, /ask_agent/);
		assert.match(prompt, /Workstream agents never write Logseq/);
		// durable internal coordination state in the daemon; dossier stays the user-facing record
		assert.match(prompt, /durable internal coordination state in the daemon/);
		assert.match(prompt, /remains the user-facing durable record/);
		// multi-agent additive model
		assert.match(prompt, /appends an agent row — additive, never overwriting/);
	});

	it("hides the plan tool from the copilot capabilities index but keeps it in other modes", async (t) => {
		const toolItems: CatalogItem[] = [
			{ type: "tools", name: "plan", description: "Submit a plan" },
			{ type: "tools", name: "bash", description: "Run a command" },
		];
		await useTempHome(t);

		useAgentMode(t, "copilot");
		const copilotPrompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems,
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		assert.match(copilotPrompt, /Tools \(1\):/);
		assert.match(copilotPrompt, /^- bash — Run a command$/m);
		assert.doesNotMatch(copilotPrompt, /^- plan —/m);

		useAgentMode(t, "work");
		const workPrompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems,
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		assert.match(workPrompt, /Tools \(2\):/);
		assert.match(workPrompt, /^- plan — Submit a plan$/m);
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
