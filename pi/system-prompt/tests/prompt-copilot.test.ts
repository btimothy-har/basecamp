import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import { assemblePrompt } from "#system-prompt/prompt.ts";
import { useAgentMode, useTempHome } from "./helpers.ts";

describe("assemblePrompt copilot", () => {
	it("loads the copilot mode and no working style", async (t) => {
		useAgentMode(t, "copilot");
		const homeDir = await useTempHome(t);
		const basecampDir = path.join(homeDir, ".pi", "basecamp");
		await fs.mkdir(path.join(basecampDir, "styles"), { recursive: true });
		await fs.writeFile(path.join(basecampDir, "styles", "engineering.md"), "CUSTOM ENGINEERING STYLE\n", "utf8");

		const prompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		// copilot is a mode: it carries its own manner, so no style file loads — but voice and
		// craft are unconditional fragments, loaded for every consumer including copilot
		assert.match(prompt, /# Repo Copilot/);
		assert.match(prompt, /# Repo Logseq/);
		assert.match(prompt, /# Voice/);
		assert.match(prompt, /# Code Craft/);
		assert.doesNotMatch(prompt, /^# Work$/m);
		assert.doesNotMatch(prompt, /# Repo Copilot Context/);
		assert.doesNotMatch(prompt, /# Your Role as an Engineer/);
		assert.doesNotMatch(prompt, /CUSTOM ENGINEERING STYLE/);
	});

	it("keeps the sequencing invariants inline and does not restate tool contracts", async (t) => {
		useAgentMode(t, "copilot");
		await useTempHome(t);

		const prompt = assemblePrompt({
			workspace: null,
			project: null,
			effectiveCwd: "/repo",
			skillItems: [],
			agentItems: [],
			contextFiles: [],
			readOnly: false,
		});

		// posture and boundaries stay in the mode fragment
		assert.match(prompt, /Copilot stages work; it does not implement in-session/);
		assert.match(prompt, /do not supervise, drive, or manage it/);
		assert.match(prompt, /Workstream agents never write Logseq/);
		assert.match(prompt, /user-facing durable record of the work item's objective, context, and decisions/);
		assert.match(prompt, /appends an agent row — additive, never overwriting/);
		// page schema and Logseq mechanics live in the copilot skill, not the mode fragment
		assert.match(prompt, /Load the `copilot` skill before writing repo memory/);
		// live state lives only in journals, so orientation must route there before the durable pages
		assert.match(prompt, /start with recent journals for current state, then the repo cockpit/);
		assert.match(prompt, /journals as state moves, dossiers when durable framing shifts/);
		// the five facts no tool description can assert
		assert.match(prompt, /\*\*List before you create\.\*\*/);
		assert.match(prompt, /An edit does not reach a running session/);
		assert.match(prompt, /Launching is not starting/);
		assert.match(prompt, /`cd <worktree-path> && pi --workstream=<slug>`/);
		assert.match(prompt, /State is pull-based/);
		// --copilot dropped the plan() sibling framing
		assert.doesNotMatch(prompt, /plan\(\)/);
		assert.doesNotMatch(prompt, /siblings, not replacements/);

		// per-call contracts belong to the tool descriptions in the API tools array
		assert.doesNotMatch(prompt, /Record-only: it does not provision a worktree/);
		assert.doesNotMatch(prompt, /bumping its version and keeping the old version/);
		assert.doesNotMatch(prompt, /provision its `copilot\/<slug>` worktree \(idempotent\)/);
		assert.doesNotMatch(prompt, /set_workstream_status/);

		// no per-tool listing in any mode: tool contracts ride the API tools array, and
		// copilot's plan() exclusion is the hard tool_call block in pi-tasks
		assert.doesNotMatch(prompt, /^Tools \(\d+\):$/m);
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
