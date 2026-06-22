/**
 * Local adapters — wires pi-core implementations into PiSwarmDependencies.
 *
 * Previously provided standalone implementations. Now delegates to pi-core's
 * registries (which pi-workspace, pi-model-aliases, etc. populate at load time).
 */

import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { registerCatalogProvider } from "pi-core/platform/catalog.ts";
import { resolveModelAlias } from "pi-core/platform/model-aliases.ts";
import { hasInvokedSkill } from "pi-core/platform/skill-tracker.ts";
import { getWorkspaceState } from "pi-core/platform/workspace.ts";
import { formatTitle, shortSessionId } from "pi-ui/src/title.ts";
import type { PiSwarmDependencies, TaskProgressSnapshot, TaskProgressTheme } from "./dependencies.ts";

// Task progress renderers — dynamically imported from pi-tasks (optional)
let taskRenderers:
	| {
			formatTaskProgressSummary: (snapshot: TaskProgressSnapshot) => string | null;
			renderCompactTaskProgressLines: (snapshot: TaskProgressSnapshot, theme: TaskProgressTheme) => string[];
	  }
	| null
	| undefined;

async function getTaskRenderers() {
	if (taskRenderers !== undefined) return taskRenderers;
	try {
		const mod = await import("pi-tasks/src/tasks/render.ts");
		taskRenderers = {
			formatTaskProgressSummary: mod.formatTaskProgressSummary,
			renderCompactTaskProgressLines: mod.renderCompactTaskProgressLines,
		};
	} catch {
		taskRenderers = null;
	}
	return taskRenderers;
}

function formatTaskProgressSummarySync(snapshot: TaskProgressSnapshot): string | null {
	const tasks = snapshot.tasks ?? [];
	const total = tasks.filter((task) => task.status !== "deleted").length;
	if (total === 0) return null;
	const completed = tasks.filter((task) => task.status === "completed").length;
	return `${completed}/${total} tasks completed`;
}

function renderCompactTaskProgressLinesSync(snapshot: TaskProgressSnapshot, theme: TaskProgressTheme): string[] {
	if (snapshot.tasks.length === 0 && !snapshot.goal) return [];
	const lines: string[] = [];
	if (snapshot.goal) {
		lines.push(`${theme.fg("dim", "Goal")}  ${snapshot.goal}`);
	}
	if (snapshot.tasks.length === 0) return lines;

	const markers: Record<string, string> = {
		completed: "✓",
		active: "→",
		pending: "☐",
		deleted: "✕",
	};

	for (let idx = 0; idx < snapshot.tasks.length && lines.length < 3 + (snapshot.goal ? 1 : 0); idx += 1) {
		const task = snapshot.tasks[idx];
		if (!task) continue;
		const marker = markers[task.status] ?? "•";
		const line = `[${task.index ?? idx}] ${marker} ${task.label}`;
		if (task.status === "active") lines.push(`${theme.fg("accent", line)}`);
		else if (task.status === "deleted") lines.push(`${theme.fg("muted", line)}`);
		else lines.push(theme.fg(task.status === "completed" ? "muted" : "dim", line));
	}

	return lines;
}

function formatTaskProgressSummary(snapshot: TaskProgressSnapshot): string | null {
	// Sync fallback; async version loaded in background
	void getTaskRenderers();
	const renderers = taskRenderers;
	if (renderers) return renderers.formatTaskProgressSummary(snapshot);
	return formatTaskProgressSummarySync(snapshot);
}

function renderCompactTaskProgressLines(snapshot: TaskProgressSnapshot, theme: TaskProgressTheme): string[] {
	const renderers = taskRenderers;
	if (renderers) return renderers.renderCompactTaskProgressLines(snapshot, theme);
	return renderCompactTaskProgressLinesSync(snapshot, theme);
}

function buildBasecampExtensionRoot(): string {
	return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

export function createLocalPiSwarmDependencies(
	basecampExtensionRoot = buildBasecampExtensionRoot(),
): PiSwarmDependencies {
	return {
		basecampExtensionRoot,
		registerCatalogProvider,
		resolveModelAlias,
		hasInvokedSkill,
		getWorkspaceState,
		formatTaskProgressSummary,
		renderCompactTaskProgressLines,
		formatTitle,
		shortSessionId,
	};
}
