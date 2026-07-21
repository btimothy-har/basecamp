import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { loadSkillsFromDir } from "@earendil-works/pi-coding-agent";

const skillsDir = path.resolve(import.meta.dirname, "..", "skills");
const frontendDesignPath = path.join(skillsDir, "frontend-design", "SKILL.md");

describe("engineering skill discovery", () => {
	it("loads cleanly and exposes frontend-design for code-first interface work", () => {
		const result = loadSkillsFromDir({ dir: skillsDir, source: "engineering-test" });
		const frontendDesign = result.skills.find((skill) => skill.name === "frontend-design");

		assert.deepEqual(result.diagnostics, []);
		assert.ok(frontendDesign);
		const content = fs.readFileSync(frontendDesignPath, "utf8");

		for (const trigger of ["frontend", "component", "prototype", "mockup", "screenshot-to-code", "responsive"]) {
			assert.match(frontendDesign.description, new RegExp(trigger, "i"));
		}
		for (const contract of [
			"runnable source code",
			"Image generation is opt-in",
			"Apply `gather`",
			"Apply `planning`",
			"Do not scaffold a parallel app",
			"self-contained HTML file",
			"`playwright-cli` skill",
		]) {
			assert.ok(content.includes(contract), `skill should explain ${contract}`);
		}
	});
});
