import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { CatalogItem } from "#core/catalog/index.ts";
import { assemblePrompt } from "../prompt.ts";
import { useAgentMode, useTempHome } from "./helpers.ts";

describe("assemblePrompt copilot", () => {
	it("composes generic work posture with the copilot style", async (t) => {
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

		// copilot is a style over the shared execution posture, not its own mode fragment
		assert.match(prompt, /# Work/);
		assert.match(prompt, /You are the repo copilot for the current repository/);
		assert.match(prompt, /# Repo Logseq/);
		assert.match(prompt, /# Code Craft/);
		assert.doesNotMatch(prompt, /# Repo Copilot Context/);
		assert.doesNotMatch(prompt, /# Your Role as an Engineer/);
		assert.doesNotMatch(prompt, /CUSTOM ENGINEERING STYLE/);
	});

	it("keeps copilot posture in the style and defers tool mechanics to the skill", async (t) => {
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

		// posture and boundaries stay in the always-on style
		assert.match(prompt, /Copilot stages work; it does not implement in-session/);
		assert.match(prompt, /do not supervise, drive, or manage it/);
		assert.match(prompt, /Workstream agents never write Logseq/);
		assert.match(prompt, /remains the user-facing durable record/);
		assert.match(prompt, /appends an agent row — additive, never overwriting/);
		assert.match(prompt, /Apply the `workstreams` skill/);
		// --copilot dropped the plan() sibling framing
		assert.doesNotMatch(prompt, /plan\(\)/);
		assert.doesNotMatch(prompt, /siblings, not replacements/);

		// cross-tool sequencing is deferred, not restated in the always-on prompt
		assert.doesNotMatch(prompt, /create_workstream/);
		assert.doesNotMatch(prompt, /launch_workstream/);
		assert.doesNotMatch(prompt, /set_workstream_status/);
		assert.doesNotMatch(prompt, /keeps the old version/);
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
