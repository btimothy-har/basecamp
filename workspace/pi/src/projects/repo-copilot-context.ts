import * as fs from "node:fs";
import * as path from "node:path";
import { readLogseqGraphDir } from "pi-core/platform/config.ts";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";

const DEFAULT_REPO_EXCERPT_CHARS = 1_500;
const DEFAULT_MAX_DOSSIERS = 3;
const DEFAULT_DOSSIER_EXCERPT_CHARS = 1_200;
const TRUNCATION_MARKER = "\n[... truncated]";

export interface BuildRepoCopilotContextOptions {
	workspace: WorkspaceState | null;
	homeDir?: string;
	maxDossiers?: number;
	repoExcerptChars?: number;
	dossierExcerptChars?: number;
}

interface RepoCopilotPaths {
	pagesDir: string;
	repoPageName: string;
	repoPagePath: string;
	dossierPagePrefix: string;
	dossierFilePrefix: string;
	dossierFileGlob: string;
}

function safeRepoIdentity(repoIdentity: string): string {
	return repoIdentity
		.trim()
		.replaceAll("/", "__")
		.replace(/[^A-Za-z0-9._-]/g, "_");
}

function clipExcerpt(content: string, maxChars: number): string {
	const limit = Math.max(0, Math.floor(maxChars));
	if (content.length <= limit) return content;
	return `${content.slice(0, limit)}${TRUNCATION_MARKER}`;
}

function buildPaths(graphDir: string, repoIdentity: string): RepoCopilotPaths {
	const pagesDir = path.join(graphDir, "pages");
	const safeIdentity = safeRepoIdentity(repoIdentity);
	const repoPageName = `repo__${safeIdentity}`;
	const dossierPagePrefix = `work__${safeIdentity}__`;
	const dossierFilePrefix = path.join(pagesDir, dossierPagePrefix);

	return {
		pagesDir,
		repoPageName,
		repoPagePath: path.join(pagesDir, `${repoPageName}.md`),
		dossierPagePrefix,
		dossierFilePrefix,
		dossierFileGlob: `${dossierFilePrefix}*.md`,
	};
}

function readOptionalFile(filePath: string): string | null {
	try {
		return fs.readFileSync(filePath, "utf8");
	} catch {
		return null;
	}
}

function listDossierFiles(pagesDir: string, dossierPagePrefix: string, maxDossiers: number): string[] {
	const limit = Math.max(0, Math.floor(maxDossiers));
	if (limit === 0) return [];

	let entries: string[];
	try {
		entries = fs.readdirSync(pagesDir);
	} catch {
		return [];
	}

	return entries
		.filter((entry) => entry.startsWith(dossierPagePrefix) && entry.endsWith(".md"))
		.sort((a, b) => a.localeCompare(b))
		.slice(0, limit)
		.map((entry) => path.join(pagesDir, entry));
}

function buildUnavailableContext(reason: string, graphDir: string | null, repoIdentity: string | null): string {
	return [
		"# Repo Copilot Context",
		"",
		"Durable repo memory is unavailable for this session; copilot mode remains usable without it.",
		`Reason: ${reason}`,
		`Configured graph path: ${graphDir ?? "unavailable"}`,
		`Repo identity: ${repoIdentity ?? "unavailable"}`,
	].join("\n");
}

export function buildRepoCopilotContext(options: BuildRepoCopilotContextOptions): string {
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

	const maxDossiers = options.maxDossiers ?? DEFAULT_MAX_DOSSIERS;
	const repoExcerptChars = options.repoExcerptChars ?? DEFAULT_REPO_EXCERPT_CHARS;
	const dossierExcerptChars = options.dossierExcerptChars ?? DEFAULT_DOSSIER_EXCERPT_CHARS;
	const paths = buildPaths(graphDir, repoIdentity);
	const repoContent = readOptionalFile(paths.repoPagePath);
	const dossierFiles = listDossierFiles(paths.pagesDir, paths.dossierPagePrefix, maxDossiers);
	const lines = [
		"# Repo Copilot Context",
		"",
		`Configured graph path: ${graphDir}`,
		`Repo identity: ${repoIdentity}`,
		`Repo cockpit logical page: [[${paths.repoPageName}]]`,
		`Repo cockpit file path: ${paths.repoPagePath}`,
		`Work dossier logical prefix: [[${paths.dossierPagePrefix}*]]`,
		`Work dossier file prefix: ${paths.dossierFilePrefix}`,
		`Work dossier file glob: ${paths.dossierFileGlob}`,
		"",
		"## Repo Cockpit Excerpt",
	];

	if (repoContent === null) {
		lines.push("not found");
	} else {
		lines.push(clipExcerpt(repoContent, repoExcerptChars));
	}

	lines.push("", "## Work Dossier Excerpts");
	if (dossierFiles.length === 0) {
		lines.push("none found");
	} else {
		for (const dossierFile of dossierFiles) {
			const dossierContent = readOptionalFile(dossierFile);
			lines.push("", `### ${path.basename(dossierFile, ".md")}`, `File path: ${dossierFile}`);
			lines.push(dossierContent === null ? "not found" : clipExcerpt(dossierContent, dossierExcerptChars));
		}
	}

	return lines.join("\n");
}
