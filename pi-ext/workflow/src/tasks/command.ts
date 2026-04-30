/**
 * /tasks command — interactive task browser + quick note subcommand.
 *
 * /tasks        — overlay: browse tasks, view details, edit notes
 * /tasks note <index> <text> — quick-add notes without the overlay
 */

import type { ExtensionAPI, ExtensionCommandContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder } from "@mariozechner/pi-coding-agent";
import { Container, matchesKey, Spacer, Text, visibleWidth } from "@mariozechner/pi-tui";
import { renderTaskDescriptionLines } from "./render";
import type { Task, TaskStatus, TasksAccess } from "./tasks";

const STATUS_MARKERS: Record<TaskStatus, string> = { completed: "✓", active: "→", pending: "☐", deleted: "✕" };

// ============================================================================
// Task List
// ============================================================================

function renderTaskList(
	tasks: readonly Task[],
	goal: string | null,
	selectedIdx: number,
	_width: number,
	theme: Theme,
): string[] {
	const lines: string[] = [];
	if (goal) {
		lines.push(`${theme.fg("dim", "Goal")}  ${goal}`, "");
	}

	if (tasks.length === 0) {
		lines.push(theme.fg("dim", "No tasks yet."));
		return lines;
	}

	const live = tasks.filter((t) => t.status !== "deleted");
	const completedCount = live.filter((t) => t.status === "completed").length;
	lines.push(theme.fg("dim", `Progress: ${completedCount}/${live.length}`), "");

	for (let i = 0; i < tasks.length; i++) {
		const task = tasks[i]!;
		const isSelected = i === selectedIdx;
		const marker = isSelected ? theme.fg("accent", "▸") : " ";
		const statusIcon = STATUS_MARKERS[task.status];

		const idxStr = theme.fg("dim", `[${i}]`);
		let label: string;
		if (task.status === "deleted") {
			label = theme.fg("dim", `${statusIcon} ${task.label}`);
		} else if (task.status === "completed") {
			label = theme.fg("dim", `${statusIcon} ${task.label}`);
		} else if (task.status === "active") {
			label = theme.fg("accent", `${statusIcon} ${task.label}`);
		} else {
			label = `${theme.fg("muted", statusIcon)} ${task.label}`;
		}

		lines.push(`${marker} ${idxStr} ${label}`);

		// Show notes indicator if present
		if (task.notes) {
			lines.push(`    ${theme.fg("dim", "📝 has notes")}`);
		}

		if (i < tasks.length - 1) lines.push("");
	}

	return lines;
}

async function showTaskList(tasks: TasksAccess, ctx: ExtensionCommandContext): Promise<number | undefined> {
	if (!ctx.hasUI) return undefined;

	const state = tasks.getState();
	if (state.tasks.length === 0) {
		ctx.ui.notify("No tasks yet.", "info");
		return undefined;
	}

	return ctx.ui.custom<number | undefined>((_tui, theme, _kb, done) => {
		let selected = 0;

		const header = new Text(theme.fg("accent", theme.bold("Tasks")), 1, 0);
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const hint = new Text(theme.fg("dim", "↑↓ navigate  Enter view  Esc close"), 1, 0);
		const listText = new Text("", 0, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(listText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const currentState = tasks.getState();
				const listLines = renderTaskList(currentState.tasks, currentState.goal, selected, width, theme);
				listText.setText(listLines.join("\n"));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				const currentState = tasks.getState();
				if (matchesKey(data, "escape")) {
					done(undefined);
				} else if (matchesKey(data, "enter")) {
					done(selected);
				} else if (matchesKey(data, "up")) {
					if (selected > 0) {
						selected--;
						container.invalidate();
					}
				} else if (matchesKey(data, "down")) {
					if (selected < currentState.tasks.length - 1) {
						selected++;
						container.invalidate();
					}
				}
			},
		};
	});
}

// ============================================================================
// Task Detail
// ============================================================================

function renderTaskDetail(task: Task, index: number, width: number, theme: Theme): string[] {
	const lines: string[] = [];
	const statusIcon = STATUS_MARKERS[task.status];

	lines.push(`${theme.fg("dim", `[${index}]`)} ${statusIcon} ${theme.fg("accent", theme.bold(task.label))}`);
	lines.push("");
	lines.push(...renderTaskDetailDescription(task.description, width, theme));
	lines.push(`${theme.fg("dim", "Criteria")}  ${task.criteria}`);

	if (task.notes) {
		lines.push("");
		lines.push(`${theme.fg("dim", "Notes")}  ${task.notes}`);
	}

	return lines;
}

function renderTaskDetailDescription(description: string, width: number, theme: Theme): string[] {
	const label = "Description";
	const prefix = `${theme.fg("dim", label)}  `;
	const prefixWidth = visibleWidth(prefix);
	const descriptionLines = renderTaskDescriptionLines(description, Math.max(0, width - prefixWidth));

	if (descriptionLines.length === 0) return [prefix];

	const lines = [`${prefix}${descriptionLines[0]!}`];
	const continuationPrefix = " ".repeat(prefixWidth);
	for (const line of descriptionLines.slice(1)) {
		lines.push(`${continuationPrefix}${line}`);
	}
	return lines;
}

async function showTaskDetail(tasks: TasksAccess, index: number, ctx: ExtensionCommandContext): Promise<boolean> {
	if (!ctx.hasUI) return false;

	const result = await ctx.ui.custom<"back" | "edit">((_tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const detailText = new Text("", 0, 0);
		const hint = new Text(theme.fg("dim", "n edit notes  Esc back"), 1, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(new Spacer(1));
		container.addChild(detailText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const task = tasks.getState().tasks[index];
				if (task) {
					detailText.setText(renderTaskDetail(task, index, width, theme).join("\n"));
				}
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape")) {
					done("back");
				} else if (data === "n" || data === "N") {
					done("edit");
				}
			},
		};
	});

	if (result === "edit") {
		const task = tasks.getState().tasks[index];
		if (!task) return true;

		const notes = await ctx.ui.input("Task notes", task.notes ?? "");
		if (notes !== undefined && notes.trim() !== "") {
			tasks.setNotes(index, notes.trim());
		}
		// Return to detail view after editing
		return showTaskDetail(tasks, index, ctx);
	}

	return true; // go back to list
}

// ============================================================================
// Subcommand: /tasks note <index> <text>
// ============================================================================

function handleNoteSubcommand(args: string, tasks: TasksAccess, ctx: ExtensionCommandContext): boolean {
	const match = args.match(/^note\s+(\d+)\s+(.+)$/s);
	if (!match) return false;

	const index = Number.parseInt(match[1]!, 10);
	const text = match[2]!.trim();
	const state = tasks.getState();

	if (index < 0 || index >= state.tasks.length) {
		ctx.ui.notify(`Invalid task index ${index}. Valid range: 0–${state.tasks.length - 1}.`, "error");
		return true;
	}

	tasks.setNotes(index, text);
	ctx.ui.notify(`Notes updated on task ${index}.`, "info");
	return true;
}

// ============================================================================
// Registration
// ============================================================================

export function registerTasksCommand(pi: ExtensionAPI, tasks: TasksAccess): void {
	pi.registerCommand("tasks", {
		description: "Browse and annotate tasks",
		handler: async (args, ctx) => {
			if (args && handleNoteSubcommand(args, tasks, ctx)) return;

			let selectedIdx = await showTaskList(tasks, ctx);
			while (selectedIdx !== undefined) {
				await showTaskDetail(tasks, selectedIdx, ctx);
				selectedIdx = await showTaskList(tasks, ctx);
			}
		},
	});
}
