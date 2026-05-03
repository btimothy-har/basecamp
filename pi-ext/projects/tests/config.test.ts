import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { resolveProjectState } from "../src/config.ts";

async function createTempHome(t: { after(fn: () => Promise<void>): void }): Promise<string> {
	const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-projects-"));
	t.after(async () => {
		await fs.rm(homeDir, { recursive: true, force: true });
	});
	return homeDir;
}

async function writeConfig(homeDir: string, config: unknown): Promise<void> {
	const configPath = path.join(homeDir, ".pi", "basecamp", "config.json");
	await fs.mkdir(path.dirname(configPath), { recursive: true });
	await fs.writeFile(configPath, JSON.stringify(config), "utf8");
}

describe("resolveProjectState", () => {
	it("returns default unprojected state when config is missing", async (t) => {
		const homeDir = await createTempHome(t);
		const repoRoot = path.join(homeDir, "repo");

		const state = resolveProjectState({ repoRoot, isRepo: true, homeDir });

		assert.equal(state.projectName, null);
		assert.equal(state.project, null);
		assert.deepEqual(state.additionalDirs, []);
		assert.equal(state.workingStyle, "engineering");
		assert.equal(state.contextContent, null);
		assert.deepEqual(state.warnings, []);
	});

	it("matches a project by repo_root and maps supported fields", async (t) => {
		const homeDir = await createTempHome(t);
		const repoRoot = path.join(homeDir, "repo");
		const extraDir = path.join(homeDir, "extra");
		await fs.mkdir(repoRoot, { recursive: true });
		await fs.mkdir(extraDir, { recursive: true });
		await writeConfig(homeDir, {
			bigquery: { default_project_id: "ignored-global" },
			projects: {
				demo: {
					repo_root: "~/repo",
					additional_dirs: ["~/extra", "~/missing"],
					description: "ignored legacy metadata",
					working_style: "research",
					context: null,
					bigquery: { default_project_id: "ignored-project" },
				},
			},
		});

		const state = resolveProjectState({ repoRoot, isRepo: true, homeDir });

		assert.equal(state.projectName, "demo");
		assert.equal(state.project?.repoRoot, repoRoot);
		assert.deepEqual(state.project?.additionalDirs, [extraDir]);
		assert.deepEqual(state.additionalDirs, [extraDir]);
		assert.equal("description" in (state.project as object), false);
		assert.equal(state.project?.workingStyle, "research");
		assert.equal(state.project?.context, null);
		assert.equal("bigquery" in (state.project as object), false);
		assert.equal(state.workingStyle, "research");
	});

	it("loads context content and applies style override", async (t) => {
		const homeDir = await createTempHome(t);
		const repoRoot = path.join(homeDir, "repo");
		const contextDir = path.join(homeDir, ".pi", "context");
		await fs.mkdir(repoRoot, { recursive: true });
		await fs.mkdir(contextDir, { recursive: true });
		await fs.writeFile(path.join(contextDir, "demo.md"), "# Demo context\n", "utf8");
		await writeConfig(homeDir, {
			projects: {
				demo: {
					repo_root: "~/repo",
					context: "demo",
					working_style: "research",
				},
			},
		});

		const state = resolveProjectState({ repoRoot, isRepo: true, homeDir, styleOverride: "planning" });

		assert.equal(state.contextContent, "# Demo context\n");
		assert.equal(state.workingStyle, "planning");
	});

	it("warns and stays unprojected when duplicate repo roots match", async (t) => {
		const homeDir = await createTempHome(t);
		const repoRoot = path.join(homeDir, "repo");
		await fs.mkdir(repoRoot, { recursive: true });
		await writeConfig(homeDir, {
			projects: {
				alpha: { repo_root: "~/repo" },
				beta: { repo_root: repoRoot },
			},
		});

		const state = resolveProjectState({ repoRoot, isRepo: true, homeDir });

		assert.equal(state.projectName, null);
		assert.equal(state.project, null);
		assert.equal(state.warnings.length, 1);
		assert.match(state.warnings[0]!, /Project detection ambiguous/);
		assert.match(state.warnings[0]!, /alpha/);
		assert.match(state.warnings[0]!, /beta/);
	});
});
