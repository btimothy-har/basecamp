import { processScoped } from "#core/platform/global-registry.ts";
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
