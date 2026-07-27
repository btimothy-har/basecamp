import * as path from "node:path";
import { readLogseqGraphDir } from "#core/host/config.ts";
import type { WorkspaceState } from "./workspace/state.ts";

export interface BuildRepoLogseqContextOptions {
	workspace: WorkspaceState | null;
	homeDir?: string;
}

/** How far back copilot may read journals before it counts as scanning the graph. */
const JOURNAL_READ_WINDOW_DAYS = 14;

interface RepoLogseqPaths {
	repoPageName: string;
	repoPagePath: string;
	workPagePrefix: string;
	workPageGlob: string;
	journalsDir: string;
}

function safeRepoIdentity(repoIdentity: string): string {
	return repoIdentity
		.trim()
		.replaceAll("/", "__")
		.replace(/[^A-Za-z0-9._-]/g, "_");
}

function buildPaths(graphDir: string, repoIdentity: string): RepoLogseqPaths {
	const pagesDir = path.join(graphDir, "pages");
	const safeIdentity = safeRepoIdentity(repoIdentity);
	const repoPageName = `repo__${safeIdentity}`;
	const workPagePrefix = `work__${safeIdentity}__`;

	return {
		repoPageName,
		repoPagePath: path.join(pagesDir, `${repoPageName}.md`),
		workPagePrefix,
		workPageGlob: `${path.join(pagesDir, workPagePrefix)}*.md`,
		journalsDir: path.join(graphDir, "journals"),
	};
}

function buildUnavailableContext(reason: string, graphDir: string | null, repoIdentity: string | null): string {
	return [
		"# Repo Logseq",
		"",
		"Durable repo memory is unavailable for this session; copilot mode remains usable without it.",
		`Reason: ${reason}`,
		`Configured graph path: ${graphDir ?? "unavailable"}`,
		`Repo identity: ${repoIdentity ?? "unavailable"}`,
		"",
		"Continue without durable repo memory. Do not scan the Logseq graph to compensate.",
	].join("\n");
}

export function buildRepoLogseqContext(options: BuildRepoLogseqContextOptions): string {
	const repoIdentity = options.workspace?.repo?.name.trim() || null;
	const graphDir = readLogseqGraphDir(options.homeDir);

	if (!repoIdentity) {
		return buildUnavailableContext("workspace repo identity is unavailable", graphDir, repoIdentity);
	}

	if (!graphDir) {
		return buildUnavailableContext(
			"Logseq graph directory is not configured or does not exist",
			graphDir,
			repoIdentity,
		);
	}

	const paths = buildPaths(graphDir, repoIdentity);

	return [
		"# Repo Logseq",
		"",
		`Durable repo memory is available for ${repoIdentity} in the configured Logseq graph at \`${graphDir}\`.`,
		"Use this memory when repo history, prior decisions, durable project facts, or active-work continuity would help answer the user well.",
		"",
		"Repo memory is three artifacts:",
		`- Journals under \`${paths.journalsDir}\` hold live state — what happened, day by day.`,
		`- Work dossiers are named like \`[[${paths.workPagePrefix}<slug>]]\` with files matching \`${paths.workPageGlob}\`; each holds durable context for one work item, never its status.`,
		`- The repo cockpit \`[[${paths.repoPageName}]]\` at \`${paths.repoPagePath}\` is a sparse repo anchor, not a work record.`,
		"",
		`Reconstruct current state from the last ${JOURNAL_READ_WINDOW_DAYS} days of journals. To trace one item further back, search the journals directory for its dossier page name.`,
		"Do not scan the whole graph. Do not read unrelated Logseq pages. Open only the repo cockpit, a specifically relevant work dossier, or journals within that window.",
		"",
		"Load the `copilot` skill before writing repo memory; it owns the page schema and the write rules.",
	].join("\n");
}
