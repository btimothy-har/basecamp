import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { listCatalogItemsByType } from "../../catalog/index.ts";
import { registerCatalogProviders } from "../../catalog/providers.ts";
import { registerSkillTool } from "../skill.ts";
import { isModelInvocationDisabled } from "../skill-content.ts";

interface SkillCommand {
	name: string;
	description?: string;
	source: "skill";
	sourceInfo: { path: string };
}

interface ToolResult {
	content: { type: string; text: string }[];
	isError?: boolean;
	details?: unknown;
}

interface RegisteredTool {
	name: string;
	execute(toolCallId: string, params: { name: string }): Promise<ToolResult>;
}

function writeSkill(dir: string, name: string, hidden: boolean): string {
	const skillDir = path.join(dir, name);
	fs.mkdirSync(skillDir, { recursive: true });
	const file = path.join(skillDir, "SKILL.md");
	const flag = hidden ? "disable-model-invocation: true\n" : "";
	fs.writeFileSync(
		file,
		`---\nname: ${name}\ndescription: ${name} skill for testing.\n${flag}---\n\n# ${name}\n\nBody.\n`,
	);
	return file;
}

function fixtures(t: TestContext): { visible: string; hidden: string } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-fixtures-"));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	return { visible: writeSkill(dir, "visible", false), hidden: writeSkill(dir, "hidden", true) };
}

function skillCommands(paths: Record<string, string>): SkillCommand[] {
	return Object.entries(paths).map(([name, p]) => ({
		name: `skill:${name}`,
		description: `${name} skill for testing.`,
		source: "skill" as const,
		sourceInfo: { path: p },
	}));
}

function captureSkillTool(commands: SkillCommand[]): RegisteredTool {
	let captured: RegisteredTool | undefined;
	const pi = {
		registerTool(tool: RegisteredTool) {
			captured = tool;
		},
		getCommands: () => commands,
	} as unknown as ExtensionAPI;
	registerSkillTool(pi);
	if (!captured) throw new Error("skill tool not registered");
	return captured;
}

describe("isModelInvocationDisabled", () => {
	it("reads the disable-model-invocation frontmatter flag", (t) => {
		const { visible, hidden } = fixtures(t);
		assert.equal(isModelInvocationDisabled(hidden), true);
		assert.equal(isModelInvocationDisabled(visible), false);
		assert.equal(isModelInvocationDisabled(path.join(os.tmpdir(), "does-not-exist-skill.md")), false);
	});
});

describe("skills capability index", () => {
	it("excludes model-hidden skills so the model never sees them listed", (t) => {
		const { visible, hidden } = fixtures(t);
		const pi = {
			getAllTools: () => [],
			getActiveTools: () => [],
			getCommands: () => skillCommands({ visible, hidden }),
		} as unknown as ExtensionAPI;

		registerCatalogProviders(pi);
		const names = listCatalogItemsByType("skills", { cwd: process.cwd() }).map((item) => item.name);

		assert.equal(names.includes("visible"), true);
		assert.equal(names.includes("hidden"), false);
	});
});

describe("skill tool", () => {
	it("refuses to load a model-hidden skill", async (t) => {
		const { hidden } = fixtures(t);
		const tool = captureSkillTool(skillCommands({ hidden }));
		const res = await tool.execute("call-1", { name: "hidden" });
		assert.equal(res.isError, true);
		assert.match(res.content[0]?.text ?? "", /user-invoked only/);
	});

	it("still loads a normal model-invocable skill", async (t) => {
		const { visible } = fixtures(t);
		const tool = captureSkillTool(skillCommands({ visible }));
		const res = await tool.execute("call-1", { name: "visible" });
		assert.notEqual(res.isError, true);
		assert.match(res.content[0]?.text ?? "", /<skill name="visible">/);
	});
});
