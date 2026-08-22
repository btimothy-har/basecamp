import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSkillTool } from "#core/skills/skill.ts";
import { resetInvokedSkills, trackSkillInvocation } from "#core/skills/tracker.ts";

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
	execute(toolCallId: string, params: { name: string; reference?: string }): Promise<ToolResult>;
}

const SKILL = "refskill";

function writeFixtures(dir: string): { skillFile: string; referenceFile: string } {
	const skillDir = path.join(dir, SKILL);
	fs.mkdirSync(path.join(skillDir, "references"), { recursive: true });
	const skillFile = path.join(skillDir, "SKILL.md");
	fs.writeFileSync(skillFile, `---\nname: ${SKILL}\ndescription: ${SKILL} skill for testing.\n---\n\n# ${SKILL}\n\nBody.\n`);
	const referenceFile = path.join(skillDir, "references", "method.md");
	fs.writeFileSync(referenceFile, "# Method\n\nShared method body.\n");
	return { skillFile, referenceFile };
}

function fixtures(t: TestContext): { skillFile: string } {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-reference-fixtures-"));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	resetInvokedSkills();
	t.after(() => resetInvokedSkills());
	return writeFixtures(dir);
}

function captureSkillTool(skillFile: string): RegisteredTool {
	let captured: RegisteredTool | undefined;
	const pi = {
		registerTool(tool: RegisteredTool) {
			captured = tool;
		},
		getCommands: () =>
			[
				{
					name: `skill:${SKILL}`,
					description: `${SKILL} skill for testing.`,
					source: "skill" as const,
					sourceInfo: { path: skillFile },
				},
			] satisfies SkillCommand[],
	} as unknown as ExtensionAPI;
	registerSkillTool(pi);
	if (!captured) throw new Error("skill tool not registered");
	return captured;
}

function resultText(res: ToolResult): string {
	return res.content[0]?.text ?? "";
}

describe("skill tool reference param", () => {
	it("returns the reference document for a loaded skill", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.notEqual(res.isError, true);
		assert.match(resultText(res), new RegExp(`^<skill-reference skill="${SKILL}">`));
		assert.match(resultText(res), /# Method/);
	});

	it("errors with load-first guidance when the skill is not loaded this session", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not loaded in this session/);
		assert.match(resultText(res), /skill\(\{ name: "refskill" \}\)/);
	});

	it("reopens the gate after a compaction reset", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const before = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });
		assert.notEqual(before.isError, true);

		resetInvokedSkills();
		const after = await tool.execute("call-2", { name: SKILL, reference: "references/method.md" });

		assert.equal(after.isError, true);
		assert.match(resultText(after), /not loaded in this session/);
	});

	it("rejects absolute reference paths", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "/etc/passwd" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("rejects traversal outside the skill directory", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "../../outside.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("rejects an empty reference that resolves to the skill directory itself", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("errors clearly when the reference file does not exist", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/missing.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /Failed to read reference file at /);
	});

	it("errors on an unregistered skill name before the gate", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: "no-such-skill", reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /No skill found with name "no-such-skill"/);
	});

	it("still loads the full skill when no reference is given", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = captureSkillTool(skillFile);

		const res = await tool.execute("call-1", { name: SKILL });

		assert.notEqual(res.isError, true);
		assert.match(resultText(res), new RegExp(`^<skill name="${SKILL}">`));
	});
});
