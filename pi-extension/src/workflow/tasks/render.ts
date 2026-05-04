import type { Theme } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";

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

export interface TaskProgressCounts {
	completed: number;
	deleted: number;
	total: number;
}

type ThemeColor = Parameters<Theme["fg"]>[0];

export interface TaskProgressRenderTheme {
	fg(color: ThemeColor, text: string): string;
}

const WINDOW_SIZE = 3;
const TASK_DESCRIPTION_LINE_LIMIT = 3;
const TASK_DESCRIPTION_ELLIPSIS = "…";
const TASK_DESCRIPTION_WIDGET_PREFIX = "  ";
const MARKERS: Record<TaskProgressStatus, string> = {
	completed: "✓",
	active: "→",
	pending: "☐",
	deleted: "✕",
};

export function countTaskProgress(snapshot: TaskProgressSnapshot): TaskProgressCounts {
	const deleted = snapshot.tasks.filter((t) => t.status === "deleted").length;
	const total = snapshot.tasks.length - deleted;
	const completed = snapshot.tasks.filter((t) => t.status === "completed").length;
	return { completed, deleted, total };
}

export function formatTaskProgressSummary(snapshot: TaskProgressSnapshot): string | null {
	const counts = countTaskProgress(snapshot);
	if (counts.total === 0) return null;
	return `${counts.completed}/${counts.total} tasks completed`;
}

export function renderTaskDescriptionLines(description: string, availableWidth: number): string[] {
	const width = Math.max(0, Math.floor(availableWidth));
	if (width === 0) return [];

	const lines: string[] = [];
	let omitted = false;

	for (const rawLine of description.split(/\r?\n/)) {
		const text = rawLine.trim();
		if (!text) continue;

		for (const wrappedLine of wrapTextWithAnsi(text, width)) {
			if (lines.length < TASK_DESCRIPTION_LINE_LIMIT) {
				lines.push(wrappedLine);
			} else {
				omitted = true;
				break;
			}
		}

		if (omitted) break;
	}

	if (omitted && lines.length > 0) {
		lines[lines.length - 1] = appendTaskDescriptionEllipsis(lines[lines.length - 1]!, width);
	}

	return lines;
}

function appendTaskDescriptionEllipsis(line: string, width: number): string {
	const ellipsisWidth = visibleWidth(TASK_DESCRIPTION_ELLIPSIS);
	if (width <= ellipsisWidth) return TASK_DESCRIPTION_ELLIPSIS;

	const baseWidth = width - ellipsisWidth;
	const base = visibleWidth(line) > baseWidth ? truncateToWidth(line, baseWidth, "") : line;
	return `${base}${TASK_DESCRIPTION_ELLIPSIS}`;
}

export function renderTaskWidgetLines(
	snapshot: TaskProgressSnapshot,
	theme: TaskProgressRenderTheme,
	width: number,
): string[] {
	if (!snapshot.goal && snapshot.tasks.length === 0) return [];

	const inner: string[] = [];
	if (snapshot.goal) {
		inner.push(`${theme.fg("dim", "Goal")}  ${snapshot.goal}`);
	}

	const contentWidth = width - 4;
	const taskLines = renderTaskProgressBody(snapshot, theme, {
		activeDescriptionWidth: Math.max(0, contentWidth - visibleWidth(TASK_DESCRIPTION_WIDGET_PREFIX)),
		includeActiveDescription: true,
		includeIndices: false,
		includeNotes: true,
	});
	if (taskLines.length > 0) {
		if (snapshot.goal) inner.push("");
		inner.push(...taskLines);
	}

	return wrapInTaskBox(inner, theme, width);
}

export function renderCompactTaskProgressLines(
	snapshot: TaskProgressSnapshot,
	theme: TaskProgressRenderTheme,
): string[] {
	if (!snapshot.goal && snapshot.tasks.length === 0) return [];

	const lines: string[] = [];
	if (snapshot.goal) {
		lines.push(`${theme.fg("dim", "Goal")}  ${snapshot.goal}`);
	}

	const taskLines = renderTaskProgressBody(snapshot, theme, {
		activeDescriptionWidth: 0,
		includeActiveDescription: false,
		includeIndices: true,
		includeNotes: false,
	});
	if (taskLines.length > 0) {
		if (snapshot.goal) lines.push("");
		lines.push(...taskLines);
	}

	return lines;
}

function renderTaskProgressBody(
	snapshot: TaskProgressSnapshot,
	theme: TaskProgressRenderTheme,
	opts: {
		activeDescriptionWidth: number;
		includeActiveDescription: boolean;
		includeIndices: boolean;
		includeNotes: boolean;
	},
): string[] {
	if (snapshot.tasks.length === 0) return [];

	const completedCount = snapshot.tasks.filter((t) => t.status === "completed").length;
	const deletedCount = snapshot.tasks.filter((t) => t.status === "deleted").length;
	const activeIdx = snapshot.tasks.findIndex((t) => t.status === "active");
	const firstPendingIdx = snapshot.tasks.findIndex((t) => t.status === "pending");
	const windowStart = activeIdx >= 0 ? activeIdx : firstPendingIdx >= 0 ? firstPendingIdx : snapshot.tasks.length;
	const windowTasks: Array<{ index: number; task: TaskProgressTask }> = [];

	for (let i = windowStart; i < snapshot.tasks.length && windowTasks.length < WINDOW_SIZE; i++) {
		const task = snapshot.tasks[i];
		if (task && task.status !== "completed") {
			windowTasks.push({ index: i, task });
		}
	}

	const pendingInWindow = windowTasks.filter(({ task }) => task.status === "pending").length;
	const totalPending = snapshot.tasks.filter((t) => t.status === "pending").length;
	const remainingCount = totalPending - pendingInWindow;
	const lines: string[] = [];
	const counts: string[] = [];

	if (completedCount > 0) counts.push(`+${completedCount} completed`);
	if (deletedCount > 0) counts.push(`+${deletedCount} deleted`);
	if (counts.length > 0) {
		lines.push(theme.fg("muted", `(${counts.join(", ")})`));
	}

	for (const { index, task } of windowTasks) {
		const notesMark = opts.includeNotes && task.notes ? theme.fg("dim", " 📝") : "";
		const marker = MARKERS[task.status];
		const displayIndex = task.index ?? index;
		const label = opts.includeIndices ? `[${displayIndex}] ${task.label}` : task.label;
		if (task.status === "deleted") {
			lines.push(`${theme.fg("dim", marker)} ${theme.fg("dim", label)}`);
		} else if (task.status === "active") {
			lines.push(`${theme.fg("accent", marker)} ${theme.fg("accent", label)}${notesMark}`);
			if (opts.includeActiveDescription && task.description) {
				for (const descriptionLine of renderTaskDescriptionLines(task.description, opts.activeDescriptionWidth)) {
					lines.push(`${TASK_DESCRIPTION_WIDGET_PREFIX}${theme.fg("dim", descriptionLine)}`);
				}
			}
		} else {
			lines.push(`${theme.fg("muted", marker)} ${label}${notesMark}`);
		}
	}

	if (remainingCount > 0) {
		lines.push(theme.fg("muted", `(+${remainingCount} to do)`));
	}

	return lines;
}

function wrapInTaskBox(lines: string[], theme: TaskProgressRenderTheme, width: number): string[] {
	const contentWidth = width - 4;
	const top = theme.fg("dim", `╭${"─".repeat(width - 2)}╮`);
	const bottom = theme.fg("dim", `╰${"─".repeat(width - 2)}╯`);
	const boxed = [top];

	for (const line of lines) {
		const wrapped = wrapTextWithAnsi(line, contentWidth);
		for (const wrappedLine of wrapped) {
			const visible = visibleWidth(wrappedLine);
			const pad = Math.max(0, contentWidth - visible);
			boxed.push(`${theme.fg("dim", "│")} ${wrappedLine}${" ".repeat(pad)} ${theme.fg("dim", "│")}`);
		}
	}

	boxed.push(bottom);
	return boxed;
}
