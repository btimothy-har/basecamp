/**
 * Config — reads ~/.pi/basecamp/config.json and resolves project state.
 *
 * The config file is managed by the Python CLI (basecamp project add/edit/remove).
 * This module is read-only — it never writes to config.json.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProjectConfig {
	dirs: string[];
	description?: string;
	working_style?: string | null;
	context?: string | null;
}

interface BasecampConfig {
	projects?: Record<string, ProjectConfig>;
	timezone?: string;
	logseq_graph?: string;
	language?: string;
	models?: Record<string, string>;
	pi_command?: string;
}

export interface SessionState {
	/** Project name (from --project flag), or null for unprojected sessions */
	projectName: string | null;
	/** Resolved project config, or null for unprojected sessions */
	project: ProjectConfig | null;
	/** Primary working directory — worktree dir if active, else project dirs[0] or ctx.cwd */
	primaryDir: string;
	/** Secondary project directories (dirs[1..]) */
	secondaryDirs: string[];
	/** Git repo name (from toplevel dirname) */
	repoName: string;
	/** Whether primaryDir is inside a git repo */
	isRepo: boolean;
	/** Git remote URL */
	remoteUrl: string | null;
	/** Scratch directory path */
	scratchDir: string;
	/** Working style name */
	workingStyle: string;
	/** Worktree directory (absolute), or null if no worktree */
	worktreeDir: string | null;
	/** Worktree label, or null if no worktree */
	worktreeLabel: string | null;
	/** Worktree branch name, or null if no worktree */
	worktreeBranch: string | null;
	/** Project context file content (cached), or null */
	contextContent: string | null;
}

// ---------------------------------------------------------------------------
// Config I/O
// ---------------------------------------------------------------------------

const CONFIG_PATH = path.join(os.homedir(), ".pi", "basecamp", "config.json");
const CONTEXT_DIR = path.join(os.homedir(), ".pi", "context");

export function getTimezone(): string | null {
	const config = readConfig();
	return typeof config.timezone === "string" && config.timezone.trim() ? config.timezone.trim() : null;
}

export function getLanguage(): string | null {
	const config = readConfig();
	return typeof config.language === "string" && config.language.trim() ? config.language.trim() : null;
}

export function getPiCommand(): string {
	const config = readConfig();
	return typeof config.pi_command === "string" && config.pi_command.trim() ? config.pi_command.trim() : "pi";
}

export function getLogseqGraph(): string | null {
	const config = readConfig();
	if (typeof config.logseq_graph !== "string" || !config.logseq_graph.trim()) return null;
	const abs = path.join(os.homedir(), config.logseq_graph.trim());
	try {
		if (fs.statSync(abs).isDirectory()) return abs;
	} catch {}
	return null;
}

/**
 * Resolve a model alias to a concrete model ID.
 * Returns the mapped model ID if found, then the fallback if provided,
 * otherwise returns the alias unchanged.
 */
export function resolveModelAlias(alias: string, fallback?: string): string {
	const config = readConfig();
	return config.models?.[alias] ?? fallback ?? alias;
}

export function readConfig(): BasecampConfig {
	try {
		const raw = fs.readFileSync(CONFIG_PATH, "utf8");
		const parsed = JSON.parse(raw);
		return typeof parsed === "object" && parsed !== null ? parsed : {};
	} catch {
		return {};
	}
}

// ---------------------------------------------------------------------------
// Directory resolution
// ---------------------------------------------------------------------------

/** Resolve a home-relative dir (as stored in config) to absolute path. */
function resolveDir(dir: string): string {
	if (path.isAbsolute(dir)) return dir;
	return path.join(os.homedir(), dir);
}

/** Validate and resolve project dirs. Returns only dirs that exist. */
function resolveDirs(dirs: string[]): string[] {
	return dirs.map(resolveDir).filter((d) => {
		try {
			return fs.statSync(d).isDirectory();
		} catch {
			return false;
		}
	});
}

// ---------------------------------------------------------------------------
// Context file loading
// ---------------------------------------------------------------------------

function loadContextFile(contextName: string): string | null {
	const filePath = path.join(CONTEXT_DIR, `${contextName}.md`);
	try {
		return fs.readFileSync(filePath, "utf8");
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------
// State builder
// ---------------------------------------------------------------------------

export interface ResolveOptions {
	projectName: string | null;
	cwd: string;
	repoName: string;
	isRepo: boolean;
	remoteUrl: string | null;
	styleOverride?: string;
}

export function resolveSessionState(opts: ResolveOptions): SessionState {
	const { projectName, cwd, repoName, isRepo, remoteUrl, styleOverride } = opts;

	let project: ProjectConfig | null = null;
	let primaryDir = cwd;
	let secondaryDirs: string[] = [];
	let workingStyle = "engineering";
	let contextContent: string | null = null;

	if (projectName) {
		const config = readConfig();
		project = config.projects?.[projectName] ?? null;

		if (project) {
			const resolved = resolveDirs(project.dirs);
			if (resolved.length > 0 && resolved[0]) {
				primaryDir = resolved[0];
				secondaryDirs = resolved.slice(1);
			}
			if (project.working_style) {
				workingStyle = project.working_style;
			}
			if (project.context) {
				contextContent = loadContextFile(project.context);
			}
		}
	}

	// Override style if --style flag was passed
	if (styleOverride) {
		workingStyle = styleOverride;
	}

	const scratchDir = path.join("/tmp/pi", repoName || path.basename(primaryDir));

	return {
		projectName,
		project,
		primaryDir,
		secondaryDirs,
		repoName,
		isRepo,
		remoteUrl,
		scratchDir,
		workingStyle,
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent,
	};
}
