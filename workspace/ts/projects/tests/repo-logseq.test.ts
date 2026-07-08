import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { buildRepoLogseqContext } from "../repo-logseq.ts";

async function createTempHome(t: TestContext): Promise<string> {
	const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-repo-logseq-"));
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

describe("buildRepoLogseqContext", () => {
	it("emits prose guidance with exact repo and work page paths", async (t) => {
		const { homeDir, graphDir, pagesDir } = await createGraph(t);
		const context = buildRepoLogseqContext({ workspace: workspace("org/repo"), homeDir });
		const repoPagePath = path.join(pagesDir, "repo__org__repo.md");
		const workPageGlob = `${path.join(pagesDir, "work__org__repo__")}*.md`;

		assert.match(context, /^# Repo Logseq/);
		assert.ok(
			context.includes(
				`Durable repo memory is available for org/repo in the configured Logseq graph at \`${graphDir}\`.`,
			),
		);
		assert.ok(context.includes("Use this memory when repo history, prior decisions, durable project facts"));
		assert.ok(
			context.includes(
				`The repo cockpit is \`[[repo__org__repo]]\` at \`${repoPagePath}\`; read it first when durable repo context matters.`,
			),
		);
		assert.ok(
			context.includes(
				`Work dossiers are task-specific pages named like \`[[work__org__repo__<slug>]]\` with files matching \`${workPageGlob}\`.`,
			),
		);
		assert.ok(context.includes("Do not scan the whole graph. Do not read unrelated Logseq pages."));
	});

	it("does not read repo page contents or scan/list work dossier files", async (t) => {
		const { homeDir, pagesDir } = await createGraph(t);
		await fs.writeFile(
			path.join(pagesDir, "repo__btimothy-har__basecamp.md"),
			"UNIQUE_REPO_PAGE_CONTENT_SHOULD_NOT_APPEAR",
			"utf8",
		);
		await fs.writeFile(
			path.join(pagesDir, "work__btimothy-har__basecamp__001.md"),
			"UNIQUE_WORK_PAGE_CONTENT_SHOULD_NOT_APPEAR",
			"utf8",
		);

		const context = buildRepoLogseqContext({ workspace: workspace(), homeDir });

		assert.equal(context.includes("UNIQUE_REPO_PAGE_CONTENT_SHOULD_NOT_APPEAR"), false);
		assert.equal(context.includes("UNIQUE_WORK_PAGE_CONTENT_SHOULD_NOT_APPEAR"), false);
		assert.equal(context.includes("work__btimothy-har__basecamp__001"), false);
		assert.equal(context.includes("Excerpt"), false);
		assert.ok(context.includes(`${path.join(pagesDir, "work__btimothy-har__basecamp__")}*.md`));
	});

	it("reports unavailable durable memory when graph config is missing", async (t) => {
		const homeDir = await createTempHome(t);
		const context = buildRepoLogseqContext({ workspace: workspace(), homeDir });

		assert.match(context, /^# Repo Logseq/);
		assert.ok(
			context.includes("Durable repo memory is unavailable for this session; copilot mode remains usable without it."),
		);
		assert.ok(context.includes("Reason: Logseq graph directory is not configured or does not exist"));
		assert.ok(context.includes("Configured graph path: unavailable"));
		assert.ok(context.includes("Repo identity: btimothy-har/basecamp"));
		assert.ok(context.includes("Continue without durable repo memory. Do not scan the Logseq graph to compensate."));
	});

	it("reports unavailable durable memory when configured graph directory is missing", async (t) => {
		const homeDir = await createTempHome(t);
		await writeRootConfig(homeDir, { logseq: { graph_dir: "~/missing-graph" } });

		const context = buildRepoLogseqContext({ workspace: workspace(), homeDir });

		assert.match(context, /^# Repo Logseq/);
		assert.ok(
			context.includes("Durable repo memory is unavailable for this session; copilot mode remains usable without it."),
		);
		assert.ok(context.includes("Reason: Logseq graph directory is not configured or does not exist"));
		assert.ok(context.includes("Configured graph path: unavailable"));
	});

	it("reports unavailable durable memory when workspace or repo identity is missing", async (t) => {
		const { homeDir, graphDir } = await createGraph(t);
		const nullWorkspaceContext = buildRepoLogseqContext({ workspace: null, homeDir });
		const noRepoContext = buildRepoLogseqContext({ workspace: workspace("repo", { repo: null }), homeDir });

		for (const context of [nullWorkspaceContext, noRepoContext]) {
			assert.match(context, /^# Repo Logseq/);
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
});
