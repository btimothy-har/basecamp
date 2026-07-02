import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { buildRepoCopilotContext } from "../repo-copilot-context.ts";

async function createTempHome(t: TestContext): Promise<string> {
	const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-repo-copilot-"));
	t.after(async () => {
		await fs.rm(homeDir, { recursive: true, force: true });
	});
	return homeDir;
}

async function writeRootConfig(homeDir: string, config: unknown): Promise<void> {
	const configPath = path.join(homeDir, ".pi", "basecamp", "config.json");
	await fs.mkdir(path.dirname(configPath), { recursive: true });
	await fs.writeFile(configPath, JSON.stringify(config), "utf8");
}

async function createGraph(t: TestContext): Promise<{ homeDir: string; graphDir: string; pagesDir: string }> {
	const homeDir = await createTempHome(t);
	const graphDir = path.join(homeDir, "logseq-graph");
	const pagesDir = path.join(graphDir, "pages");
	await fs.mkdir(pagesDir, { recursive: true });
	await writeRootConfig(homeDir, { logseq: { graph_dir: "~/logseq-graph" } });
	return { homeDir, graphDir, pagesDir };
}

function workspace(repoName = "btimothy-har/basecamp", overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: "/repo",
		scratchDir: "/tmp/pi/repo",
		repo: {
			isRepo: true,
			name: repoName,
			root: "/repo",
			remoteUrl: "git@github.com:btimothy-har/basecamp.git",
		},
		protectedRoot: "/repo",
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

describe("buildRepoCopilotContext", () => {
	it("includes configured repo cockpit and capped dossier excerpts", async (t) => {
		const { homeDir, graphDir, pagesDir } = await createGraph(t);
		await fs.writeFile(
			path.join(pagesDir, "repo__btimothy-har__basecamp.md"),
			"# Basecamp cockpit\nStable repo notes",
			"utf8",
		);
		await fs.writeFile(
			path.join(pagesDir, "work__btimothy-har__basecamp__001.md"),
			"# Work one\nFirst dossier",
			"utf8",
		);
		await fs.writeFile(
			path.join(pagesDir, "work__btimothy-har__basecamp__002.md"),
			"# Work two\nSecond dossier",
			"utf8",
		);
		await fs.writeFile(path.join(pagesDir, "not_this_repo.md"), "ignored secret", "utf8");

		const context = buildRepoCopilotContext({ workspace: workspace(), homeDir });

		assert.match(context, /^# Repo Copilot Context/);
		assert.match(context, new RegExp(`Configured graph path: ${graphDir.replaceAll("/", "\\/")}`));
		assert.ok(context.includes("Repo identity: btimothy-har/basecamp"));
		assert.ok(context.includes("# Basecamp cockpit\nStable repo notes"));
		assert.ok(context.includes("### work__btimothy-har__basecamp__001"));
		assert.ok(context.includes("# Work one\nFirst dossier"));
		assert.ok(context.includes("### work__btimothy-har__basecamp__002"));
		assert.ok(context.includes("# Work two\nSecond dossier"));
		assert.equal(context.includes("ignored secret"), false);
	});

	it("derives safe Logseq page names and exact paths for org/repo identities", async (t) => {
		const { homeDir, graphDir } = await createGraph(t);
		const pagesDir = path.join(graphDir, "pages");
		const context = buildRepoCopilotContext({ workspace: workspace("org/repo"), homeDir });

		assert.ok(context.includes("Repo cockpit logical page: [[repo__org__repo]]"));
		assert.ok(context.includes(`Repo cockpit file path: ${path.join(pagesDir, "repo__org__repo.md")}`));
		assert.ok(context.includes("Work dossier logical prefix: [[work__org__repo__*]]"));
		assert.ok(context.includes(`Work dossier file prefix: ${path.join(pagesDir, "work__org__repo__")}`));
		assert.ok(context.includes(`Work dossier file glob: ${path.join(pagesDir, "work__org__repo__")}*.md`));
	});

	it("reports unavailable durable memory when graph config is missing", async (t) => {
		const homeDir = await createTempHome(t);
		const context = buildRepoCopilotContext({ workspace: workspace(), homeDir });

		assert.match(context, /^# Repo Copilot Context/);
		assert.ok(
			context.includes("Durable repo memory is unavailable for this session; copilot mode remains usable without it."),
		);
		assert.ok(context.includes("Reason: Logseq graph directory is not configured or does not exist"));
		assert.ok(context.includes("Configured graph path: unavailable"));
		assert.ok(context.includes("Repo identity: btimothy-har/basecamp"));
	});

	it("reports unavailable durable memory when configured graph directory is missing", async (t) => {
		const homeDir = await createTempHome(t);
		await writeRootConfig(homeDir, { logseq: { graph_dir: "~/missing-graph" } });

		const context = buildRepoCopilotContext({ workspace: workspace(), homeDir });

		assert.ok(
			context.includes("Durable repo memory is unavailable for this session; copilot mode remains usable without it."),
		);
		assert.ok(context.includes("Reason: Logseq graph directory is not configured or does not exist"));
		assert.ok(context.includes("Configured graph path: unavailable"));
	});

	it("reports unavailable durable memory when workspace or repo identity is missing", async (t) => {
		const { homeDir, graphDir } = await createGraph(t);
		const nullWorkspaceContext = buildRepoCopilotContext({ workspace: null, homeDir });
		const noRepoContext = buildRepoCopilotContext({ workspace: workspace("repo", { repo: null }), homeDir });

		for (const context of [nullWorkspaceContext, noRepoContext]) {
			assert.ok(
				context.includes(
					"Durable repo memory is unavailable for this session; copilot mode remains usable without it.",
				),
			);
			assert.ok(context.includes("Reason: workspace repo identity is unavailable"));
			assert.ok(context.includes(`Configured graph path: ${graphDir}`));
			assert.ok(context.includes("Repo identity: unavailable"));
		}
	});

	it("outputs exact paths plus not-found markers when pages are missing", async (t) => {
		const homeDir = await createTempHome(t);
		const graphDir = path.join(homeDir, "logseq-graph");
		await fs.mkdir(graphDir, { recursive: true });
		await writeRootConfig(homeDir, { logseq: { graph_dir: graphDir } });
		const pagesDir = path.join(graphDir, "pages");

		const context = buildRepoCopilotContext({ workspace: workspace(), homeDir });

		assert.ok(context.includes(`Repo cockpit file path: ${path.join(pagesDir, "repo__btimothy-har__basecamp.md")}`));
		assert.ok(context.includes(`Work dossier file glob: ${path.join(pagesDir, "work__btimothy-har__basecamp__")}*.md`));
		assert.ok(context.includes("## Repo Cockpit Excerpt\nnot found"));
		assert.ok(context.includes("## Work Dossier Excerpts\nnone found"));
	});

	it("caps dossier count and marks clipped excerpts", async (t) => {
		const { homeDir, pagesDir } = await createGraph(t);
		await fs.writeFile(
			path.join(pagesDir, "repo__btimothy-har__basecamp.md"),
			"cockpit content is longer than cap",
			"utf8",
		);
		await fs.writeFile(path.join(pagesDir, "work__btimothy-har__basecamp__001.md"), "dossier one long content", "utf8");
		await fs.writeFile(path.join(pagesDir, "work__btimothy-har__basecamp__002.md"), "dossier two long content", "utf8");
		await fs.writeFile(
			path.join(pagesDir, "work__btimothy-har__basecamp__003.md"),
			"dossier three long content",
			"utf8",
		);

		const context = buildRepoCopilotContext({
			workspace: workspace(),
			homeDir,
			maxDossiers: 2,
			repoExcerptChars: 7,
			dossierExcerptChars: 8,
		});

		assert.ok(context.includes("cockpit\n[... truncated]"));
		assert.ok(context.includes("dossier \n[... truncated]"));
		assert.ok(context.includes("### work__btimothy-har__basecamp__001"));
		assert.ok(context.includes("### work__btimothy-har__basecamp__002"));
		assert.equal(context.includes("work__btimothy-har__basecamp__003"), false);
		assert.equal(context.includes("dossier three long content"), false);
	});
});
