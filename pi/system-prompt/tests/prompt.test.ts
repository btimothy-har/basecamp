import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import { setAgentMode } from "#core/agent-mode/index.ts";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import { assemblePrompt } from "../prompt.ts";
import { useDefaultAgentMode, useTempHome } from "./helpers.ts";

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
		assert.match(prompt, /### File Length/);
		assert.match(prompt, /350 lines for TypeScript and HTML/);
		assert.match(prompt, /800 for SQL/);
		assert.match(prompt, /tighter limit/);
		assert.match(prompt, /advisory, not a gate/);
		assert.match(prompt, /## Git & GitHub/);
		assert.match(prompt, /Use `git` and `gh` directly in bash like a normal developer\./);
	});

	it("keeps skill lifecycle guidance in primary and agent prompts", async (t) => {
		useDefaultAgentMode(t);
		await useTempHome(t);
		const options = {
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			toolItems: [],
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		};
		const assertLifecycle = (prompt: string): void => {
			assert.equal(prompt.match(/Apply a skill whose instructions are already in context/g)?.length, 1);
			assert.match(prompt, /load it with `skill` when they are not/);
			assert.doesNotMatch(prompt, /\b(?:Always )?[Ii]nvoke\b[^\n]*\bskills?\b/);
		};
		const modeExpectations = [
			["work", /Apply the `agents` skill to select and brief them/],
			["analysis", /Apply the `data-analysis` skill before substantial analysis or research/],
			["planning", /Apply `planning` for discovery\/convergence methodology/],
		] as const;

		for (const [mode, expected] of modeExpectations) {
			setAgentMode(mode);
			const prompt = assemblePrompt(options);
			assertLifecycle(prompt);
			assert.match(prompt, expected);
		}

		const agentPrompt = assemblePrompt({ ...options, agentPrompt: "custom agent prompt", readOnly: true });
		assertLifecycle(agentPrompt);
		assert.match(agentPrompt, /Always apply any relevant Python skill guidance/);
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
		assert.match(prompt, /File `edit`\/`write` calls may modify the protected checkout directly\./);
		assert.match(prompt, /Commits and mutating git commands still require an active execution worktree\./);
		assert.match(prompt, /Subagents do not inherit unsafe-edit authority\./);
		assert.doesNotMatch(
			prompt,
			/⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory\. Do not edit the protected repository checkout\./,
		);
	});

	it("emits environment facts and the runtime block as one contiguous category", async (t) => {
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
		});

		const factsAt = prompt.indexOf("# Environment");
		const runtimeAt = prompt.indexOf("Is directory a git repo:");
		assert.ok(factsAt > prompt.indexOf("Available in this session:"));
		assert.ok(runtimeAt > factsAt);

		// nothing from another category may separate the authored facts from the runtime block
		const between = prompt.slice(factsAt, runtimeAt);
		assert.doesNotMatch(between, /Available in this session:|# Project Context|# Your Role as an Engineer/);
		assert.equal(prompt.match(/Scratch directory:/g)?.length, 1);
	});
});
