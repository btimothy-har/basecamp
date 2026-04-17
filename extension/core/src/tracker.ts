/**
 * Tracker — persistent context widget below the editor.
 *
 * Tracks a goal and an ordered task list with three states:
 *   ✓ completed  →  active  ·  pending
 *
 * Four tools:
 *   - update_goal: set or change the session goal
 *   - create_tasks: set the ordered task list (replaces existing)
 *   - start_task: mark a task as active
 *   - complete_task: mark a task as done
 *
 * Widget shows a sliding window of 3 open tasks with collapse
 * counters for completed/remaining items.
 *
 * State is persisted via appendEntry for session resume.
 */

import type { ToolResultMessage } from "@mariozechner/pi-ai";
import type { ExtensionAPI, ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";

// ============================================================================
// Types
// ============================================================================

type TaskStatus = "pending" | "active" | "completed";

interface Task {
	label: string;
	status: TaskStatus;
}

interface TrackerState {
	goal: string | null;
	tasks: Task[];
}

// ============================================================================
// State helpers
// ============================================================================

function requireTasks(state: TrackerState, index: number): Task {
	if (state.tasks.length === 0) throw new Error("No tasks exist. Use create_tasks first.");
	if (!Number.isInteger(index) || index < 0 || index >= state.tasks.length) {
		throw new Error(`Invalid task index ${index}. Valid range: 0–${state.tasks.length - 1}.`);
	}
	return state.tasks[index]!;
}

// ============================================================================
// Widget Rendering
// ============================================================================

const WINDOW_SIZE = 3;

function renderWidget(
	state: TrackerState,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	_bold: Theme["bold"],
	width: number,
): string[] {
	const hasContent = state.goal || state.tasks.length > 0;
	if (!hasContent) return [];

	const inner: string[] = [];
	const boxWidth = width;

	if (state.goal) {
		inner.push(`${fg("dim", "Goal")}  ${state.goal}`);
	}

	if (state.tasks.length > 0) {
		const completedCount = state.tasks.filter((t) => t.status === "completed").length;

		// Find window start: first active task, or first pending if none active
		const activeIdx = state.tasks.findIndex((t) => t.status === "active");
		const firstPendingIdx = state.tasks.findIndex((t) => t.status === "pending");
		const windowStart = activeIdx >= 0 ? activeIdx : firstPendingIdx >= 0 ? firstPendingIdx : state.tasks.length;

		// Window: up to WINDOW_SIZE open tasks from windowStart
		const windowTasks: Task[] = [];
		for (let i = windowStart; i < state.tasks.length && windowTasks.length < WINDOW_SIZE; i++) {
			const task = state.tasks[i];
			if (task && task.status !== "completed") {
				windowTasks.push(task);
			}
		}

		// Remaining pending tasks after the window
		const pendingInWindow = windowTasks.filter((t) => t.status === "pending").length;
		const totalPending = state.tasks.filter((t) => t.status === "pending").length;
		const remainingCount = totalPending - pendingInWindow;

		if (state.goal) {
			inner.push("");
		}

		if (completedCount > 0) {
			inner.push(fg("muted", `(+${completedCount} completed)`));
		}

		for (const task of windowTasks) {
			if (task.status === "active") {
				inner.push(`${fg("accent", "→")} ${fg("accent", task.label)}`);
			} else {
				inner.push(`${fg("muted", "☐")} ${task.label}`);
			}
		}

		if (remainingCount > 0) {
			inner.push(fg("muted", `(+${remainingCount} to do)`));
		}
	}

	// Box-draw border
	const contentWidth = boxWidth - 4;
	const top = fg("dim", `╭${"─".repeat(boxWidth - 2)}╮`);
	const bottom = fg("dim", `╰${"─".repeat(boxWidth - 2)}╯`);
	const lines: string[] = [top];
	for (const line of inner) {
		const wrapped = wrapTextWithAnsi(line, contentWidth);
		for (const wl of wrapped) {
			const vw = visibleWidth(wl);
			const pad = Math.max(0, contentWidth - vw);
			lines.push(`${fg("dim", "│")} ${wl}${" ".repeat(pad)} ${fg("dim", "│")}`);
		}
	}
	lines.push(bottom);
	return lines;
}

// ============================================================================
// Steer message
// ============================================================================

function buildSteerContent(state: TrackerState): string | null {
	if (!state.goal) return null;

	const lines = [`Current progress:`, `Goal: ${state.goal}`];

	if (state.tasks.length > 0) {
		const completedCount = state.tasks.filter((t) => t.status === "completed").length;
		lines.push(`Completed: ${completedCount}/${state.tasks.length}`);
		lines.push("");

		// Show only open tasks with indices
		for (let i = 0; i < state.tasks.length; i++) {
			const t = state.tasks[i]!;
			if (t.status === "completed") continue;
			const marker = t.status === "active" ? "→" : "☐";
			lines.push(`  [${i}] ${marker} ${t.label}`);
		}
	}

	lines.push(
		"",
		"Call start_task before beginning work on a task. Call complete_task when done. If the plan changes, call create_tasks with the updated list.",
	);
	return lines.join("\n");
}

// ============================================================================
// Tool render helpers
// ============================================================================

function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

function renderPartial(theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

// ============================================================================
// Detail types for tool results (used for persistence/replay)
// ============================================================================

interface GoalDetails {
	action: "update_goal";
	goal: string;
}
interface TasksDetails {
	action: "create_tasks";
	tasks: string[];
}
interface TaskOpDetails {
	action: "start_task" | "complete_task";
	task: number;
	label: string;
}

// ============================================================================
// Registration
// ============================================================================

export function registerTracker(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;
	let state: TrackerState = { goal: null, tasks: [] };

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		const hasContent = state.goal || state.tasks.length > 0;
		if (!hasContent) {
			ctx.ui.setWidget("basecamp-tracker", undefined, { placement: "belowEditor" });
			return;
		}

		ctx.ui.setWidget(
			"basecamp-tracker",
			(_tui, theme) => {
				const fg = theme.fg.bind(theme);
				const bold = theme.bold.bind(theme);
				let cachedLines: string[] | null = null;
				let cachedWidth = 0;

				return {
					invalidate() {
						cachedLines = null;
					},
					render(width: number): string[] {
						if (cachedLines && cachedWidth === width) return cachedLines;
						cachedWidth = width;
						cachedLines = renderWidget(state, fg, bold, width);
						return cachedLines;
					},
				};
			},
			{ placement: "belowEditor" },
		);
	}

	function persistState(): void {
		pi.appendEntry("tracker-state", state);
	}

	// --- Tool: update_goal ---
	pi.registerTool({
		name: "update_goal",
		label: "Update Goal",
		description: "Set or change the session goal. Call at the start of any task to establish what success looks like.",
		promptSnippet: "Set the session goal",
		parameters: Type.Object({
			goal: Type.String({ description: "What success looks like — concrete and verifiable (1 sentence)" }),
		}),
		async execute(_id, params) {
			state.goal = params.goal;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: "Goal updated." }],
				details: { action: "update_goal" as const, goal: params.goal },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const goal = (args.goal as string) || "...";
			const preview = goal.length > 60 ? `${goal.slice(0, 60)}...` : goal;
			return new Text(theme.fg("toolTitle", theme.bold("update_goal ")) + theme.fg("dim", preview), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("goal updated", theme);
		},
	});

	// --- Tool: create_tasks ---
	pi.registerTool({
		name: "create_tasks",
		label: "Create Tasks",
		description:
			"Set the ordered task list for the current goal. Replaces any existing tasks. Requires a goal to be set first.",
		promptSnippet: "Set the task list for the current goal",
		parameters: Type.Object({
			tasks: Type.Array(Type.String(), { description: "Ordered list of task descriptions" }),
		}),
		async execute(_id, params) {
			if (!state.goal) {
				throw new Error("Cannot create tasks without a goal. Call update_goal first.");
			}
			state.tasks = params.tasks.map((label) => ({ label, status: "pending" as TaskStatus }));
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: `Created ${params.tasks.length} tasks.` }],
				details: { action: "create_tasks" as const, tasks: params.tasks },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const tasks = args.tasks as string[] | undefined;
			const count = tasks?.length ?? 0;
			return new Text(theme.fg("toolTitle", theme.bold("create_tasks ")) + theme.fg("dim", `${count} tasks`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess(`${state.tasks.length} tasks created`, theme);
		},
	});

	// --- Tool: start_task ---
	pi.registerTool({
		name: "start_task",
		label: "Start Task",
		description: "Mark a task as active by index. Only one task can be active at a time.",
		promptSnippet: "Mark a task as active",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);

			if (target.status === "completed") {
				throw new Error(`Task ${params.task} is already completed.`);
			}

			// Clear any previously active task back to pending
			for (const t of state.tasks) {
				if (t.status === "active") t.status = "pending";
			}
			target.status = "active";
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: `Started: ${target.label}` }],
				details: { action: "start_task" as const, task: params.task, label: target.label },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("start_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task started", theme);
		},
	});

	// --- Tool: complete_task ---
	pi.registerTool({
		name: "complete_task",
		label: "Complete Task",
		description: "Mark a task as completed by index.",
		promptSnippet: "Mark a task as completed",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);

			if (target.status === "completed") {
				throw new Error(`Task ${params.task} is already completed.`);
			}

			target.status = "completed";
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: `Completed: ${target.label}` }],
				details: { action: "complete_task" as const, task: params.task, label: target.label },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(
				theme.fg("toolTitle", theme.bold("complete_task ")) + theme.fg("dim", `[${idx}] ${preview}`),
				0,
				0,
			);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task completed", theme);
		},
	});

	// --- Tool: escalate ---
	const NAV_TYPE_ANSWER = "✎ Type answer...";
	const NAV_BACK = "← Previous";
	const NAV_SKIP = "→ Skip";

	interface EscalateQuestion {
		question: string;
	}

	/** Build the select choices for a question, including navigation controls. */
	function buildChoices(hasExistingAnswer: boolean, showBack: boolean, isMulti: boolean): string[] {
		const choices = [NAV_TYPE_ANSWER];
		if (isMulti) {
			if (showBack) choices.push(NAV_BACK);
			if (hasExistingAnswer) choices.push(NAV_SKIP);
		}
		return choices;
	}

	/** Navigate through questions with select-based controls. */
	async function runQuestionLoop(
		ui: ExtensionContext["ui"],
		questions: EscalateQuestion[],
	): Promise<Map<number, string> | "dismissed"> {
		const answers = new Map<number, string>();
		const isMulti = questions.length > 1;
		let index = 0;

		while (index < questions.length) {
			const q = questions[index]!;
			const existing = answers.get(index);
			const title = isMulti ? `(${index + 1}/${questions.length}) ${q.question}` : q.question;
			const choices = buildChoices(existing !== undefined, index > 0, isMulti);

			const picked = await ui.select(title, choices);

			if (!picked) {
				// Esc: go back if possible, otherwise dismiss
				if (index > 0) {
					index--;
					continue;
				}
				return "dismissed";
			}

			if (picked === NAV_BACK) {
				index--;
				continue;
			}

			if (picked === NAV_SKIP) {
				index++;
				continue;
			}

			if (picked === NAV_TYPE_ANSWER) {
				const typed = await ui.input(title, existing);
				if (typed) {
					answers.set(index, typed);
					index++;
				}
			}
		}

		return answers;
	}

	pi.registerTool({
		name: "escalate",
		label: "Escalate",
		description:
			"Surface a blocker or decision to the user. Use when you need user input, hit ambiguity, or are stuck. Pauses execution until the user responds.",
		promptSnippet: "Pause and ask the user for a decision or help with a blocker",
		parameters: Type.Object({
			questions: Type.Array(Type.String(), {
				description: "Questions to ask the user, presented in sequence with back/forward navigation",
			}),
		}),
		async execute(_id, params, _signal, _onUpdate, execCtx) {
			const questions: EscalateQuestion[] = params.questions.map((q) => ({ question: q }));

			if (!execCtx.hasUI) {
				const summary = questions.map((q) => `[escalation] ${q.question}`).join("\n");
				return {
					content: [{ type: "text", text: summary }],
					details: { questions: questions.map((q) => q.question), answers: null },
				};
			}

			const result = await runQuestionLoop(execCtx.ui, questions);

			if (result === "dismissed") {
				return {
					content: [{ type: "text", text: "User dismissed without answering." }],
					details: { questions: questions.map((q) => q.question), answers: null },
				};
			}

			// Format answers: single question returns plain text, multi returns labeled pairs
			if (questions.length === 1) {
				const answer = result.get(0) ?? "";
				return {
					content: [{ type: "text", text: answer }],
					details: { questions: params.questions, answers: [answer] },
				};
			}

			const answerLines = questions.map((q, i) => `${q.question}\n→ ${result.get(i) ?? "(no answer)"}`);
			return {
				content: [{ type: "text", text: answerLines.join("\n\n") }],
				details: {
					questions: questions.map((q) => q.question),
					answers: questions.map((_, i) => result.get(i) ?? null),
				},
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const qs = args.questions as string[] | undefined;
			const preview = qs?.[0] ?? "...";
			const trimmed = preview.length > 60 ? `${preview.slice(0, 60)}...` : preview;
			const suffix = qs && qs.length > 1 ? ` (+${qs.length - 1} more)` : "";
			return new Text(theme.fg("toolTitle", theme.bold("escalate ")) + theme.fg("dim", trimmed + suffix), 0, 0);
		},
		renderResult(result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			const details = result.details as { answers: (string | null)[] | null };
			if (!details?.answers) {
				const { Text } = require("@mariozechner/pi-tui");
				return new Text(theme.fg("warning", "⚠") + theme.fg("dim", " dismissed"), 0, 0);
			}
			const count = details.answers.filter(Boolean).length;
			return renderSuccess(`${count} answer${count !== 1 ? "s" : ""} received`, theme);
		},
	});

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		state = { goal: null, tasks: [] };

		// Restore from persisted entries
		const entries = sessionCtx.sessionManager.getEntries();
		const trackerEntry = entries
			.filter((e) => e.type === "custom" && (e as { customType?: string }).customType === "tracker-state")
			.pop() as { data?: TrackerState } | undefined;

		if (trackerEntry?.data) {
			if (trackerEntry.data.goal) state.goal = trackerEntry.data.goal;
			if (trackerEntry.data.tasks) state.tasks = trackerEntry.data.tasks;
		}

		// Replay tool calls from the branch to reconstruct current state
		for (const entry of sessionCtx.sessionManager.getBranch()) {
			if (entry.type !== "message" || entry.message.role !== "toolResult") continue;
			const msg = entry.message as ToolResultMessage;
			if (!msg.details) continue;

			const d = msg.details as GoalDetails | TasksDetails | TaskOpDetails;

			switch (d.action) {
				case "update_goal":
					state.goal = d.goal;
					break;
				case "create_tasks":
					state.tasks = d.tasks.map((label) => ({ label, status: "pending" as TaskStatus }));
					break;
				case "start_task":
					if (state.tasks[d.task]) {
						for (const t of state.tasks) {
							if (t.status === "active") t.status = "pending";
						}
						state.tasks[d.task]!.status = "active";
					}
					break;
				case "complete_task":
					if (state.tasks[d.task]) {
						state.tasks[d.task]!.status = "completed";
					}
					break;
			}
		}

		updateWidget();
	});

	// --- before_agent_start: inject progress reminder ---
	pi.on("before_agent_start", async (_event, agentCtx) => {
		if (!agentCtx.hasUI) return;

		const content = buildSteerContent(state);
		if (content) {
			pi.sendMessage(
				{
					customType: "tracker-context",
					content,
					display: false,
				},
				{ deliverAs: "steer" },
			);
		}
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		ctx = null;
	});
}
