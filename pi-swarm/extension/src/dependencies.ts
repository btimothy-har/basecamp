import type { Theme } from "@earendil-works/pi-coding-agent";

type ThemeColor = Parameters<Theme["fg"]>[0];

export type CatalogType = "tools" | "skills" | "agents" | (string & {});

export interface CatalogItem {
	type: CatalogType;
	name: string;
	description: string;
	path?: string;
	meta?: Record<string, string>;
}

export interface CatalogContext {
	cwd: string;
}

export interface CatalogProvider {
	id: string;
	list: (ctx: CatalogContext) => CatalogItem[];
}

export interface RepoContext {
	root: string;
}

export interface WorkspaceWorktree {
	path: string;
}

export interface WorkspaceState {
	launchCwd: string;
	repo: RepoContext | null;
	activeWorktree: WorkspaceWorktree | null;
	protectedRoot: string | null;
}

export type TaskProgressStatus = "pending" | "active" | "completed" | "deleted";

export interface TaskProgressTask {
	label: string;
	status: TaskProgressStatus;
	index?: number;
	description?: string;
	notes?: string | null;
}

export interface TaskProgressSnapshot {
	goal: string | null;
	tasks: TaskProgressTask[];
}

export interface TaskProgressTheme {
	fg(color: ThemeColor, text: string): string;
}

export interface PiSwarmDependencies {
	basecampExtensionRoot: string;
	registerCatalogProvider: (provider: CatalogProvider) => void;
	resolveModelAlias: (alias: string) => string | undefined;
	hasInvokedSkill: (name: string) => boolean;
	getWorkspaceState: () => WorkspaceState | null;
	readSkillContent: (filePath: string) => string | null;
	buildSkillBlock: (name: string, content: string) => string;
	formatTaskProgressSummary: (snapshot: TaskProgressSnapshot) => string | null;
	renderCompactTaskProgressLines: (snapshot: TaskProgressSnapshot, theme: TaskProgressTheme) => string[];
	formatTitle: (title: string, tag: string) => string;
	shortSessionId: (sessionId: string) => string;
}
