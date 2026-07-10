import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { processScoped } from "../global-registry.ts";
import { registerWorkspaceAllowedRootsProvider, requireWorkspaceState } from "./workspace/state.ts";

// --- Project config + resolved state cell ---

export interface ProjectConfig {
	repoRoot: string;
	additionalDirs: string[];
	workingStyle?: string | null;
	context?: string | null;
}

export interface ProjectState {
	projectName: string | null;
	project: ProjectConfig | null;
	additionalDirs: string[];
	workingStyle: string;
	contextContent: string | null;
	warnings: string[];
}

interface ProjectRuntime {
	state: ProjectState | null;
}

// Surviving state (legacy key name kept so /reload across the rename keeps state).
const getProjectRuntime = processScoped<ProjectRuntime>("pi.projects.runtime", () => ({ state: null }));

export function resetProjectRuntime(): void {
	getProjectRuntime().state = null;
}

export function getProjectState(): ProjectState | null {
	return getProjectRuntime().state;
}

export function requireProjectState(): ProjectState {
	const state = getProjectState();
	if (!state) throw new Error("Project state is not initialized");
	return state;
}

export function setProjectState(state: ProjectState): void {
	getProjectRuntime().state = state;
}

// --- Resolution from workspace/projects.json ---

interface RawProjectConfig {
	repo_root?: unknown;
	additional_dirs?: unknown;
	working_style?: unknown;
	context?: unknown;
}

export interface ResolveProjectOptions {
	repoRoot: string;
	isRepo: boolean;
	styleOverride?: string;
	homeDir?: string;
	configPath?: string;
	contextDir?: string;
}

interface ProjectDetection {
	projectName: string | null;
	project: ProjectConfig | null;
	contextName: string | null;
	warnings: string[];
}

const BASECAMP_WORKSPACE_RELATIVE_DIR = path.join(".pi", "basecamp", "workspace");

function defaultHomeDir(homeDir?: string): string {
	return homeDir ?? os.homedir();
}

function defaultWorkspaceDir(homeDir: string): string {
	return path.join(homeDir, BASECAMP_WORKSPACE_RELATIVE_DIR);
}

function defaultConfigPath(homeDir: string, configPath?: string): string {
	return configPath ?? path.join(defaultWorkspaceDir(homeDir), "projects.json");
}

function defaultContextDir(homeDir: string, contextDir?: string): string {
	return contextDir ?? path.join(defaultWorkspaceDir(homeDir), "context");
}

export function resolveConfigDir(dir: string, homeDir = os.homedir()): string {
	if (dir === "~") return homeDir;
	if (dir.startsWith("~/")) return path.join(homeDir, dir.slice(2));
	if (path.isAbsolute(dir)) return dir;
	return path.join(homeDir, dir);
}

function readProjects(configPath: string): Record<string, RawProjectConfig> {
	try {
		const parsed: unknown = JSON.parse(fs.readFileSync(configPath, "utf8"));
		if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
		const projects = (parsed as { projects?: unknown }).projects;
		if (!projects || typeof projects !== "object" || Array.isArray(projects)) return {};
		return Object.fromEntries(
			Object.entries(projects).filter((entry): entry is [string, RawProjectConfig] => {
				const [, value] = entry;
				return !!value && typeof value === "object" && !Array.isArray(value);
			}),
		);
	} catch {
		return {};
	}
}

function configuredAdditionalDirs(project: RawProjectConfig): string[] {
	if (!Array.isArray(project.additional_dirs)) return [];
	return project.additional_dirs.filter((dir): dir is string => typeof dir === "string" && dir.length > 0);
}

function resolveExistingDirs(dirs: string[], homeDir: string): string[] {
	return dirs
		.map((dir) => resolveConfigDir(dir, homeDir))
		.filter((dir) => {
			try {
				return fs.statSync(dir).isDirectory();
			} catch {
				return false;
			}
		});
}

function optionalString(value: unknown): string | undefined {
	return typeof value === "string" ? value : undefined;
}

function optionalStringOrNull(value: unknown): string | null | undefined {
	return typeof value === "string" || value === null ? value : undefined;
}

function mapProjectConfig(project: RawProjectConfig, homeDir: string): ProjectConfig | null {
	const repoRoot = optionalString(project.repo_root);
	if (!repoRoot?.trim()) return null;

	return {
		repoRoot: path.resolve(resolveConfigDir(repoRoot, homeDir)),
		additionalDirs: resolveExistingDirs(configuredAdditionalDirs(project), homeDir),
		...(optionalStringOrNull(project.working_style) !== undefined
			? { workingStyle: optionalStringOrNull(project.working_style) }
			: {}),
		...(optionalStringOrNull(project.context) !== undefined ? { context: optionalStringOrNull(project.context) } : {}),
	};
}

function detectProjectByRepoRoot(
	repoRoot: string,
	isRepo: boolean,
	configPath: string,
	homeDir: string,
): ProjectDetection {
	if (!isRepo) return { projectName: null, project: null, contextName: null, warnings: [] };

	const target = path.resolve(repoRoot);
	const matches: Array<[string, ProjectConfig]> = [];

	for (const [name, rawProject] of Object.entries(readProjects(configPath))) {
		const project = mapProjectConfig(rawProject, homeDir);
		if (!project) continue;
		if (project.repoRoot === target) matches.push([name, project]);
	}

	if (matches.length === 1) {
		const [projectName, project] = matches[0]!;
		return { projectName, project, contextName: project.context ?? null, warnings: [] };
	}

	if (matches.length > 1) {
		return {
			projectName: null,
			project: null,
			contextName: null,
			warnings: [
				`Project detection ambiguous: repo_root ${target} is configured for ${matches
					.map(([name]) => name)
					.join(", ")}; session is unprojected.`,
			],
		};
	}

	return { projectName: null, project: null, contextName: null, warnings: [] };
}

function loadContextFile(contextDir: string, contextName: string): string | null {
	try {
		return fs.readFileSync(path.join(contextDir, `${contextName}.md`), "utf8");
	} catch {
		return null;
	}
}

export function resolveProjectState(options: ResolveProjectOptions): ProjectState {
	const homeDir = defaultHomeDir(options.homeDir);
	const configPath = defaultConfigPath(homeDir, options.configPath);
	const contextDir = defaultContextDir(homeDir, options.contextDir);
	const detection = detectProjectByRepoRoot(options.repoRoot, options.isRepo, configPath, homeDir);
	const project = detection.project;
	let workingStyle = "engineering";
	let contextContent: string | null = null;

	if (project) {
		if (project.workingStyle) workingStyle = project.workingStyle;
		if (detection.contextName) contextContent = loadContextFile(contextDir, detection.contextName);
	}

	if (options.styleOverride?.trim()) workingStyle = options.styleOverride.trim();

	return {
		projectName: detection.projectName,
		project,
		additionalDirs: project?.additionalDirs ?? [],
		workingStyle,
		contextContent,
		warnings: detection.warnings,
	};
}

// --- Session wiring: resolve the project at session_start (after workspace init) ---

function setProjectEnv(): void {
	process.env.BASECAMP_PROJECT = getProjectState()?.projectName ?? "";
}

export function registerProjectSession(pi: ExtensionAPI): void {
	pi.registerFlag("style", {
		description: "Override working style (e.g. engineering, advisor)",
		type: "string",
	});
	pi.registerFlag("agent-prompt", {
		description: "Agent prompt file — replaces working style + system.md (used by worker spawner)",
		type: "string",
	});

	registerWorkspaceAllowedRootsProvider({
		id: "projects",
		roots: () => getProjectState()?.additionalDirs ?? [],
	});

	pi.on("session_start", async (_event, ctx) => {
		resetProjectRuntime();

		const workspaceState = requireWorkspaceState();
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const projectState = resolveProjectState({
			repoRoot: workspaceState.repo?.root ?? workspaceState.launchCwd,
			isRepo: workspaceState.repo !== null,
			styleOverride,
		});
		setProjectState(projectState);
		setProjectEnv();

		for (const warning of requireProjectState().warnings) {
			ctx.ui.notify(`projects: ${warning}`, "warning");
		}
	});
}
