/**
 * Config — reads ~/.pi/basecamp/config.json and resolves project state.
 *
 * The config file is managed by the Python CLI's `basecamp config` menu.
 * This module is read-only — it never writes to config.json.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type BigQueryOutputFormat = "csv" | "json";

export interface BigQueryConfig {
	enabled?: boolean;
	default_project_id?: string;
	default_location?: string;
	default_output_format?: BigQueryOutputFormat;
	default_max_rows?: number;
	auto_dry_run?: boolean;
}

export interface ProjectConfig {
	repo_root: string;
	additional_dirs: string[];
	description?: string;
	working_style?: string | null;
	context?: string | null;
	bigquery?: BigQueryConfig | null;
}

export interface BasecampConfig {
	projects?: Record<string, ProjectConfig>;
	bigquery?: BigQueryConfig | null;
	timezone?: string;
	logseq_graph?: string;
	language?: string;
	models?: Record<string, string>;
	pi_command?: string;
	worktree_branch_prefix?: string;
}

export interface SessionState {
	/** Detected project name, or null for unprojected sessions */
	projectName: string | null;
	/** Resolved project config, or null for unprojected sessions */
	project: ProjectConfig | null;
	/** Directory Pi was launched from */
	launchCwd: string;
	/** Git repository root / protected checkout (launch cwd for non-repo sessions) */
	repoRoot: string;
	/** Additional project directories */
	additionalDirs: string[];
	/** Git repo name (from toplevel dirname) */
	repoName: string;
	/** Whether launchCwd is inside a git repo */
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
	/** Non-fatal project detection warnings to surface at session start */
	projectWarnings: string[];
	/** Unsafe edit mode: allows edit/write to target protected checkout directly */
	unsafeEdit: boolean;
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

/**
 * Returns [binary, ...prefixArgs] so multi-word commands like "devx pi" work
 * with spawn()/execFile() which require the binary as a separate first arg.
 */
export function getPiCommand(): [string, ...string[]] {
	const config = readConfig();
	const raw = typeof config.pi_command === "string" && config.pi_command.trim() ? config.pi_command.trim() : "pi";
	const parts = raw.split(/\s+/);
	return parts as [string, ...string[]];
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

/** Resolve BigQuery defaults with per-project values overriding global values. */
export function resolveBigQueryConfig(project?: ProjectConfig | null): BigQueryConfig {
	const config = readConfig();
	return {
		...(config.bigquery ?? {}),
		...(project?.bigquery ?? {}),
	};
}

export function getWorktreeBranchPrefix(): string {
	const config = readConfig();
	const prefix = config.worktree_branch_prefix;
	// Empty string or undefined → default to "wt/"
	if (!prefix?.trim()) return "wt/";
	return prefix;
}

// ---------------------------------------------------------------------------
// Directory resolution
// ---------------------------------------------------------------------------

/** Resolve a home-relative dir (as stored in config) to absolute path. */
export function resolveConfigDir(dir: string): string {
	if (dir === "~") return os.homedir();
	if (dir.startsWith("~/")) return path.join(os.homedir(), dir.slice(2));
	if (path.isAbsolute(dir)) return dir;
	return path.join(os.homedir(), dir);
}

/** Validate and resolve project dirs. Returns only dirs that exist. */
function resolveExistingDirs(dirs: string[]): string[] {
	return dirs.map(resolveConfigDir).filter((d) => {
		try {
			return fs.statSync(d).isDirectory();
		} catch {
			return false;
		}
	});
}

function projectAdditionalDirs(project: ProjectConfig): string[] {
	return Array.isArray(project.additional_dirs) ? project.additional_dirs : [];
}

/** Resolve a project's repository root and additional directories. */
export function resolveProjectDirectories(project: ProjectConfig): string[] {
	return [resolveConfigDir(project.repo_root), ...resolveExistingDirs(projectAdditionalDirs(project))];
}

export function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

/** Compute the cwd tools should use for the current session state. */
export function getSessionEffectiveCwd(state: SessionState): string {
	if (!state.worktreeDir) return state.launchCwd;

	if (isPathWithin(state.launchCwd, state.repoRoot)) {
		const relative = path.relative(state.repoRoot, state.launchCwd);
		return path.resolve(state.worktreeDir, relative);
	}

	return state.worktreeDir;
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
	launchCwd: string;
	repoRoot: string;
	repoName: string;
	isRepo: boolean;
	remoteUrl: string | null;
	styleOverride?: string;
}

interface ProjectDetection {
	projectName: string | null;
	project: ProjectConfig | null;
	warnings: string[];
}

function detectProjectByRepoRoot(repoRoot: string, isRepo: boolean): ProjectDetection {
	if (!isRepo) return { projectName: null, project: null, warnings: [] };

	const target = path.resolve(repoRoot);
	const projects = readConfig().projects ?? {};
	const matches: Array<[string, ProjectConfig]> = [];

	for (const [name, project] of Object.entries(projects)) {
		if (!project || typeof project.repo_root !== "string" || !project.repo_root.trim()) continue;
		const configuredRoot = path.resolve(resolveConfigDir(project.repo_root));
		if (configuredRoot === target) {
			matches.push([name, project]);
		}
	}

	if (matches.length === 1) {
		const [projectName, project] = matches[0]!;
		return { projectName, project, warnings: [] };
	}

	if (matches.length > 1) {
		return {
			projectName: null,
			project: null,
			warnings: [
				`Project detection ambiguous: repo_root ${target} is configured for ${matches
					.map(([name]) => name)
					.join(", ")}; session is unprojected.`,
			],
		};
	}

	return { projectName: null, project: null, warnings: [] };
}

export function resolveSessionState(opts: ResolveOptions): SessionState {
	const launchCwd = path.resolve(opts.launchCwd);
	const repoRoot = path.resolve(opts.repoRoot);
	const { repoName, isRepo, remoteUrl, styleOverride } = opts;

	const detection = detectProjectByRepoRoot(repoRoot, isRepo);
	const project = detection.project;
	const projectName = detection.projectName;
	let additionalDirs: string[] = [];
	let workingStyle = "engineering";
	let contextContent: string | null = null;

	if (project) {
		additionalDirs = resolveExistingDirs(projectAdditionalDirs(project));
		if (project.working_style) {
			workingStyle = project.working_style;
		}
		if (project.context) {
			contextContent = loadContextFile(project.context);
		}
	}

	// Override style if --style flag was passed
	if (styleOverride?.trim()) {
		workingStyle = styleOverride.trim();
	}

	const scratchDir = path.join("/tmp/pi", repoName || path.basename(repoRoot));

	return {
		projectName,
		project,
		launchCwd,
		repoRoot,
		additionalDirs,
		repoName,
		isRepo,
		remoteUrl,
		scratchDir,
		workingStyle,
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent,
		projectWarnings: detection.warnings,
		unsafeEdit: false,
	};
}
