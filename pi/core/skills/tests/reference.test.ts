import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSkillLifecycle, resetInvokedSkills, trackSkillInvocation } from "#core/skills/tracker.ts";
import { captureSkillTool, renderToolCall, renderToolResult, skillCommands, type ToolResult } from "./harness.ts";

const SKILL = "refskill";

interface SkillFixture {
	skillFile: string;
	referenceFile: string;
}

function writeFixtures(dir: string, hidden = false): SkillFixture {
	const skillDir = path.join(dir, SKILL);
	fs.mkdirSync(path.join(skillDir, "references"), { recursive: true });
	const skillFile = path.join(skillDir, "SKILL.md");
	const flag = hidden ? "disable-model-invocation: true\n" : "";
	fs.writeFileSync(
		skillFile,
		`---\nname: ${SKILL}\ndescription: ${SKILL} skill for testing.\n${flag}---\n\n# ${SKILL}\n\nBody.\n`,
	);
	const referenceFile = path.join(skillDir, "references", "method.md");
	fs.writeFileSync(referenceFile, "# Method\n\nShared method body.\n");
	return { skillFile, referenceFile };
}

function fixtures(t: TestContext, hidden = false): SkillFixture {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-reference-fixtures-"));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	resetInvokedSkills();
	t.after(() => resetInvokedSkills());
	return writeFixtures(dir, hidden);
}

function toolFor(skillFile: string) {
	return captureSkillTool(skillCommands({ [SKILL]: skillFile }));
}

function resultText(res: ToolResult): string {
	return res.content[0]?.text ?? "";
}

describe("skill tool reference param", () => {
	it("returns the reference document for a loaded skill", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.notEqual(res.isError, true);
		assert.match(resultText(res), new RegExp(`^<skill-reference skill="${SKILL}">`));
		assert.match(resultText(res), /# Method/);
	});

	it("errors with load-first guidance when the skill is not loaded this session", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /is not recorded as loaded in this session/);
		assert.match(resultText(res), /skill\(\{ name: "refskill" \}\)/);
	});

	it("rejects absolute reference paths", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "/etc/passwd" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("rejects traversal outside the skill directory", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "../../outside.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("rejects a symlink that escapes the skill directory", async (t) => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "skill-reference-symlink-"));
		t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
		resetInvokedSkills();
		t.after(() => resetInvokedSkills());
		const { skillFile } = writeFixtures(dir);
		const secret = path.join(dir, "secret.md");
		fs.writeFileSync(secret, "# Secret outside the skill\n");
		fs.symlinkSync(secret, path.join(path.dirname(skillFile), "references", "planted.md"));

		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);
		const res = await tool.execute("call-1", { name: SKILL, reference: "references/planted.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
		assert.doesNotMatch(resultText(res), /Secret outside the skill/);
	});

	it("rejects an empty reference that resolves to the skill directory itself", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /not a valid skill-relative path/);
	});

	it("errors clearly when the reference file does not exist", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/missing.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /Failed to read reference file at /);
	});

	it("errors on an unregistered skill name before the gate", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: "no-such-skill", reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /No skill found with name "no-such-skill"/);
	});

	it("refuses a reference request for a model-hidden skill before the gate", async (t) => {
		const { skillFile } = fixtures(t, true);
		const tool = toolFor(skillFile);
		trackSkillInvocation(SKILL);

		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /user-invoked only/);
	});

	it("still loads the full skill when no reference is given", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);

		const res = await tool.execute("call-1", { name: SKILL });

		assert.notEqual(res.isError, true);
		assert.match(resultText(res), new RegExp(`^<skill name="${SKILL}">`));
	});
});

describe("skill tool renderers", () => {
	it("renders the reference form of renderCall with name and reference", (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);

		const rendered = renderToolCall(tool, { name: SKILL, reference: "references/method.md" });

		assert.match(rendered, new RegExp(SKILL));
		assert.match(rendered, /references\/method\.md/);
	});

	it("renders a successful reference load distinctly from a full load", (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);

		const reference = renderToolResult(tool, {
			content: [{ type: "text", text: `<skill-reference skill="${SKILL}">\n# Method\n</skill-reference>` }],
		});
		const full = renderToolResult(tool, {
			content: [{ type: "text", text: `<skill name="${SKILL}">\n# Body\n</skill>` }],
		});

		assert.match(reference, /refskill reference loaded/);
		assert.match(full, /refskill loaded/);
	});

	it("renders reference errors as reference failures and other errors neutrally", (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);

		const gate = renderToolResult(tool, {
			content: [{ type: "text", text: `Skill "${SKILL}" is not recorded as loaded in this session.` }],
			isError: true,
		});
		const invalid = renderToolResult(tool, {
			content: [{ type: "text", text: `Reference "../../x.md" is not a valid skill-relative path.` }],
			isError: true,
		});
		const hidden = renderToolResult(tool, {
			content: [{ type: "text", text: `Skill "${SKILL}" is user-invoked only (via /skill:${SKILL}).` }],
			isError: true,
		});

		assert.match(gate, /skill reference failed/);
		assert.match(invalid, /skill reference failed/);
		assert.match(hidden, /skill processed/);
	});
});

describe("reference gate lifecycle wiring", () => {
	interface LifecycleHandlers {
		session_start: ((event: { reason: string }) => unknown)[];
		session_compact: (() => unknown)[];
		input: ((event: { text: string }) => unknown)[];
	}

	function captureLifecycle(): LifecycleHandlers {
		const handlers: LifecycleHandlers = { session_start: [], session_compact: [], input: [] };
		const pi = {
			on(event: string, handler: (...args: never[]) => unknown) {
				const list = handlers[event as keyof LifecycleHandlers];
				if (list) (list as ((...args: never[]) => unknown)[]).push(handler);
			},
		} as unknown as ExtensionAPI;
		registerSkillLifecycle(pi);
		return handlers;
	}

	it("reopens the gate when session_compact fires", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		const handlers = captureLifecycle();
		trackSkillInvocation(SKILL);

		for (const handler of handlers.session_compact) handler();
		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.equal(res.isError, true);
		assert.match(resultText(res), /is not recorded as loaded in this session/);
	});

	it("preserves the gate across /reload but resets on startup", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		const handlers = captureLifecycle();
		trackSkillInvocation(SKILL);

		for (const handler of handlers.session_start) handler({ reason: "reload" });
		const afterReload = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });
		assert.notEqual(afterReload.isError, true);

		for (const handler of handlers.session_start) handler({ reason: "startup" });
		const afterStartup = await tool.execute("call-2", { name: SKILL, reference: "references/method.md" });
		assert.equal(afterStartup.isError, true);
		assert.match(resultText(afterStartup), /is not recorded as loaded in this session/);
	});

	it("records /skill:name user input so the gate recognizes slash-loaded skills", async (t) => {
		const { skillFile } = fixtures(t);
		const tool = toolFor(skillFile);
		const handlers = captureLifecycle();
		resetInvokedSkills();

		for (const handler of handlers.input) handler({ text: `/skill:${SKILL} some args` });
		const res = await tool.execute("call-1", { name: SKILL, reference: "references/method.md" });

		assert.notEqual(res.isError, true);
		assert.match(resultText(res), /# Method/);
	});
});
