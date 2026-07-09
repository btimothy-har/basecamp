import * as path from "node:path";
import { readLogseqGraphDir } from "../platform/config.ts";
import type { WorkspaceState } from "../platform/workspace.ts";

export interface BuildRepoLogseqContextOptions {
	workspace: WorkspaceState | null;
	homeDir?: string;
}

interface RepoLogseqPaths {
	repoPageName: string;
	repoPagePath: string;
	workPagePrefix: string;
	workPageGlob: string;
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
		`The repo cockpit is \`[[${paths.repoPageName}]]\` at \`${paths.repoPagePath}\`; read it first when durable repo context matters.`,
		`Work dossiers are task-specific pages named like \`[[${paths.workPagePrefix}<slug>]]\` with files matching \`${paths.workPageGlob}\`.`,
		"Do not scan the whole graph. Do not read unrelated Logseq pages. Open only the repo cockpit or a specifically relevant work dossier when the task calls for durable memory.",
	].join("\n");
}
