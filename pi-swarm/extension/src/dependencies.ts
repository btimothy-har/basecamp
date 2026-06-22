/**
 * Re-exports shared type contracts from pi-core and pi-tasks.
 *
 * These were previously hand-rolled duplicates. Now that pi-core and pi-tasks
 * are installable packages, we import directly from them.
 */

// Catalog types from pi-core
export type { CatalogContext, CatalogItem, CatalogProvider, CatalogType } from "pi-core/platform/catalog.ts";

import type { CatalogProvider } from "pi-core/platform/catalog.ts";

// Workspace types from pi-core
export type { RepoContext, WorkspaceState, WorkspaceWorktree } from "pi-core/platform/workspace.ts";

import type { WorkspaceState } from "pi-core/platform/workspace.ts";

// Task progress types from pi-tasks (the canonical source)
import type { TaskProgressSnapshot, TaskProgressStatus, TaskProgressTask } from "pi-tasks/src/tasks/render.ts";

export type { TaskProgressSnapshot, TaskProgressStatus, TaskProgressTask };

// Theme types (local to pi-swarm — used for rendering)
import type { Theme } from "@earendil-works/pi-coding-agent";

export type ThemeColor = Parameters<Theme["fg"]>[0];

export interface TaskProgressTheme {
	fg(color: ThemeColor, text: string): string;
}

/**
 * PiSwarmDependencies provides functions that pi-swarm needs.
 * In the direct-import model, these are sourced from pi-core/pi-ui.
 * This interface is retained for backward compat during the transition.
 */
export interface PiSwarmDependencies {
	basecampExtensionRoot: string;
	registerCatalogProvider: (provider: CatalogProvider) => void;
	resolveModelAlias: (alias: string) => string | undefined;
	hasInvokedSkill: (name: string) => boolean;
	getWorkspaceState: () => WorkspaceState | null;
	formatTaskProgressSummary: (snapshot: TaskProgressSnapshot) => string | null;
	renderCompactTaskProgressLines: (snapshot: TaskProgressSnapshot, theme: TaskProgressTheme) => string[];
	formatTitle: (title: string, tag: string) => string;
	shortSessionId: (sessionId: string) => string;
}
