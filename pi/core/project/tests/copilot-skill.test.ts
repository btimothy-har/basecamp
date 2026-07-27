import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadSkillsFromDir } from "@earendil-works/pi-coding-agent";
import { copilotSkillPath, registerCopilotSkill } from "#core/project/logseq.ts";

const originalArgv = process.argv;

function setCopilotLaunch(launched: boolean): void {
	process.argv = launched ? ["node", "pi", "--copilot"] : ["node", "pi"];
}

interface ResourceContribution {
	skillPaths?: string[];
}
type ResourceHandler = () => ResourceContribution;

function createMockPi(): { pi: ExtensionAPI; resourceHandlers: ResourceHandler[] } {
	const resourceHandlers: ResourceHandler[] = [];
	const pi = {
		on(event: string, handler: ResourceHandler) {
			if (event === "resources_discover") resourceHandlers.push(handler);
		},
	};
	return { pi: pi as unknown as ExtensionAPI, resourceHandlers };
}

function withCopilotLaunch(t: TestContext, launched: boolean): void {
	setCopilotLaunch(launched);
	t.after(() => {
		process.argv = originalArgv;
	});
}

describe("copilot skill registration", () => {
	it("offers the skill to copilot sessions", (t) => {
		withCopilotLaunch(t, true);
		const { pi, resourceHandlers } = createMockPi();

		registerCopilotSkill(pi);

		assert.equal(resourceHandlers.length, 1);
		assert.deepEqual(resourceHandlers[0]?.(), { skillPaths: [copilotSkillPath] });
	});

	it("offers nothing outside copilot sessions", (t) => {
		withCopilotLaunch(t, false);
		const { pi, resourceHandlers } = createMockPi();

		registerCopilotSkill(pi);

		assert.equal(resourceHandlers.length, 1);
		assert.deepEqual(resourceHandlers[0]?.(), {});
	});

	it("re-reads the launch value on every discovery", (t) => {
		withCopilotLaunch(t, false);
		const { pi, resourceHandlers } = createMockPi();

		registerCopilotSkill(pi);
		assert.deepEqual(resourceHandlers[0]?.(), {});

		setCopilotLaunch(true);
		assert.deepEqual(resourceHandlers[0]?.(), { skillPaths: [copilotSkillPath] });
	});
});

describe("copilot skill", () => {
	it("loads cleanly and is model-invocable", () => {
		const result = loadSkillsFromDir({ dir: path.dirname(copilotSkillPath), source: "copilot-skill-test" });
		const skill = result.skills[0];
		const content = fs.readFileSync(copilotSkillPath, "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(skill?.name, "copilot");
		assert.doesNotMatch(content, /disable-model-invocation:\s*true/);
	});

	it("states the three artifacts and the write prohibitions", () => {
		const content = fs.readFileSync(copilotSkillPath, "utf8");

		for (const contract of [
			"journals/YYYY_MM_DD.md",
			"pages/work__<org>__<repo>__<slug>.md",
			"pages/repo__<org>__<repo>.md",
			"type:: work-dossier",
			"type:: repo-cockpit",
			"## Objective",
			"## Decisions",
			"Nest repo-first",
			"Record events, never workstream status",
			"list_workstreams",
			"Propose before writing",
			"Never write `title::`",
			"wrong to commit to the repository",
		]) {
			assert.ok(content.includes(contract), `skill should state: ${contract}`);
		}

		for (const banned of ["status::", "priority::", "updated::", "workstreams::"]) {
			assert.ok(content.includes(banned), `skill should name the banned property ${banned}`);
		}
	});
});
