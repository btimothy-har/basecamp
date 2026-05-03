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

const projectRuntimeKey = Symbol.for("pi.projects.runtime");

type GlobalWithProjectRuntime = typeof globalThis & {
	[projectRuntimeKey]?: ProjectRuntime;
};

function getProjectRuntime(): ProjectRuntime {
	const globalObject = globalThis as GlobalWithProjectRuntime;
	globalObject[projectRuntimeKey] ??= { state: null };
	return globalObject[projectRuntimeKey];
}

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
