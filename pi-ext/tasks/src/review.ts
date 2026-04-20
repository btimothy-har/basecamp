/**
 * Review overlays — interactive TUI components for plan review.
 *
 * Three views:
 *   - List: browse review items, drill into any
 *   - Drill-down: view content + feedback, approve/revise/edit
 *   - Edit: write or modify feedback text
 *   - Read-only: shows approved plan (for /plan after approval)
 *
 * Goal + Context are merged into a single review item.
 * Design, Success, Boundaries are individual items.
 */

import type { ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import { Container, Editor, type EditorTheme, matchesKey, Spacer, Text } from "@mariozechner/pi-tui";
import type { GoalCycle, ReviewState, Task } from "./tasks";

// ============================================================================
// Types
// ============================================================================

interface PlanSection {
	content: string;
	review: ReviewState;
}

export interface PlanDraft {
	goal: PlanSection;
	context: PlanSection;
	design: PlanSection;
	success: PlanSection;
	boundaries: PlanSection;
	tasks: Task[];
	tasksReview: ReviewState;
}

export const SECTION_NAMES = ["goal", "context", "design", "success", "boundaries"] as const;
export type SectionName = (typeof SECTION_NAMES)[number];

/** Sections that appear as individual review items (not goal/context). */
const INDIVIDUAL_SECTIONS: SectionName[] = ["design", "success", "boundaries"];

type ReviewItem = { kind: "goalContext" } | { kind: "section"; name: SectionName } | { kind: "tasks" };

// ============================================================================
// Helpers
// ============================================================================

export function sectionDisplayName(name: SectionName): string {
	return name.charAt(0).toUpperCase() + name.slice(1);
}

function reviewMarker(review: ReviewState, theme: Theme): string {
	let state: string;
	if (review.approved === true) state = theme.fg("success", "✓");
	else if (review.approved === false) state = theme.fg("warning", "★");
	else state = theme.fg("muted", "☐");

	const note = review.feedback ? theme.fg("dim", " 📝") : "";
	return `${state}${note}`;
}

function countPending(draft: PlanDraft): number {
	let count = 0;
	// Goal+Context share review state — count as one item
	if (draft.goal.review.approved === null) count++;
	for (const name of INDIVIDUAL_SECTIONS) {
		if (draft[name].review.approved === null) count++;
	}
	// Tasks are a single collective review item
	if (draft.tasksReview.approved === null) count++;
	return count;
}

function getListItems(draft: PlanDraft): ReviewItem[] {
	const items: ReviewItem[] = [];
	items.push({ kind: "goalContext" });
	for (const name of INDIVIDUAL_SECTIONS) {
		items.push({ kind: "section", name });
	}
	if (draft.tasks.length > 0) {
		items.push({ kind: "tasks" });
	}
	return items;
}

function getItemReview(draft: PlanDraft, item: ReviewItem): ReviewState {
	if (item.kind === "goalContext") return draft.goal.review;
	if (item.kind === "section") return draft[item.name].review;
	return draft.tasksReview;
}

function setItemReview(draft: PlanDraft, item: ReviewItem, review: ReviewState): void {
	if (item.kind === "goalContext") {
		// Sync both goal and context to the same review state
		draft.goal.review = review;
		draft.context.review = review;
	} else if (item.kind === "section") {
		draft[item.name].review = review;
	} else {
		draft.tasksReview = review;
	}
}

// ============================================================================
// Rendering
// ============================================================================

function renderListView(items: ReviewItem[], selected: number, draft: PlanDraft, theme: Theme): string[] {
	const lines: string[] = [];

	for (let i = 0; i < items.length; i++) {
		const item = items[i]!;
		const cursor = i === selected ? theme.fg("accent", "▸") : " ";

		if (item.kind === "goalContext") {
			const marker = reviewMarker(draft.goal.review, theme);
			const preview = draft.goal.content.length > 40 ? `${draft.goal.content.slice(0, 40)}…` : draft.goal.content;
			lines.push(`${cursor} ${marker} ${theme.bold("Goal")}  ${theme.fg("dim", preview)}`);
		} else if (item.kind === "section") {
			const marker = reviewMarker(draft[item.name].review, theme);
			const content = draft[item.name].content;
			const preview = content.length > 40 ? `${content.slice(0, 40)}…` : content;
			lines.push(`${cursor} ${marker} ${theme.bold(sectionDisplayName(item.name))}  ${theme.fg("dim", preview)}`);
		} else {
			const marker = reviewMarker(draft.tasksReview, theme);
			lines.push(`${cursor} ${marker} ${theme.bold("Tasks")}  ${theme.fg("dim", `${draft.tasks.length} tasks`)}`);
		}
	}

	return lines;
}

function renderDrillDownContent(draft: PlanDraft, item: ReviewItem, theme: Theme): string[] {
	const lines: string[] = [];

	if (item.kind === "goalContext") {
		const marker = reviewMarker(draft.goal.review, theme);
		lines.push(`${marker} ${theme.fg("accent", theme.bold("Goal"))}`);
		lines.push("");
		lines.push(draft.goal.content);
		lines.push("");
		lines.push(`${theme.fg("dim", "Context")}  ${draft.context.content}`);
	} else if (item.kind === "section") {
		const section = draft[item.name];
		const marker = reviewMarker(section.review, theme);
		lines.push(`${marker} ${theme.fg("accent", theme.bold(sectionDisplayName(item.name)))}`);
		lines.push("");
		lines.push(section.content);
	}
	// Tasks use showTaskCards, not drill-down

	return lines;
}

// ============================================================================
// List view — navigate + select
// ============================================================================

export async function showReviewOverlay(draft: PlanDraft, ctx: ExtensionContext): Promise<"submit" | "decline"> {
	let lastSelected = 0;

	while (true) {
		const items = getListItems(draft);

		const selection = await ctx.ui.custom<number | "submit" | "decline">((_tui, theme, _kb, done) => {
			let selected = Math.min(lastSelected, items.length - 1);
			const defaultHint = theme.fg("dim", "[↑↓: Navigate]  [Space: Drill in]  [s: Submit]  [Esc: Decline]");

			const header = new Text(theme.fg("accent", theme.bold("Plan Review")), 1, 0);
			const border = new DynamicBorder((s: string) => theme.fg("border", s));
			const hint = new Text(defaultHint, 1, 0);
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
					listText.setText(renderListView(items, selected, draft, theme).join("\n"));
					return container.render(width);
				},
				invalidate: () => container.invalidate(),
				handleInput: (data: string) => {
					hint.setText(defaultHint);
					if (matchesKey(data, "escape")) {
						done("decline");
					} else if (data === "s" || data === "S") {
						const pending = countPending(draft);
						if (pending > 0) {
							hint.setText(theme.fg("warning", `${pending} item${pending > 1 ? "s" : ""} still pending review`));
							container.invalidate();
							return;
						}
						done("submit");
					} else if (data === " " || matchesKey(data, "enter")) {
						done(selected);
					} else if (matchesKey(data, "up")) {
						if (selected > 0) {
							selected--;
							container.invalidate();
						}
					} else if (matchesKey(data, "down")) {
						if (selected < items.length - 1) {
							selected++;
							container.invalidate();
						}
					}
				},
			};
		});

		if (selection === "submit") return "submit";
		if (selection === "decline") return "decline";

		lastSelected = selection;
		const item = items[selection]!;
		if (item.kind === "tasks") {
			await showTaskCards(draft, ctx);
		} else {
			await showDrillDown(draft, item, ctx);
		}
	}
}

// ============================================================================
// Drill-down view — content + inline feedback editor
//
// Focus: content (hotkeys active) ↔ editor (typing mode)
// a = approve, r = revise, Esc = back (content) or clear/unfocus (editor)
// ============================================================================

async function showDrillDown(draft: PlanDraft, item: ReviewItem, ctx: ExtensionContext): Promise<void> {
	const action = await ctx.ui.custom<"approve" | "revise" | "back">((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const contentText = new Text("", 0, 0);
		const feedbackLabel = new Text("", 0, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const editor = new Editor(tui, editorTheme, { paddingX: 0 });
		const currentFeedback = getItemReview(draft, item).feedback ?? "";
		editor.setText(currentFeedback);
		editor.focused = false;

		let editorFocused = false;

		editor.onSubmit = (value: string) => {
			// Enter in editor: save feedback and unfocus
			const trimmed = value.trim();
			setItemReview(draft, item, { approved: getItemReview(draft, item).approved, feedback: trimmed || null });
			editorFocused = false;
			editor.focused = false;
			updateHint();
			container.invalidate();
		};

		function updateHint(): void {
			if (editorFocused) {
				hint.setText(theme.fg("dim", "[Enter: Save]  [Esc: Clear/Back]"));
				feedbackLabel.setText(theme.fg("accent", "Feedback"));
			} else {
				const parts = ["[a: Approve]", "[r: Revise]", "[↓: Feedback]"];
				parts.push("[Esc: Back]");
				hint.setText(theme.fg("dim", parts.join("  ")));
				const fb = getItemReview(draft, item).feedback;
				if (fb) {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}\n${fb}`);
				} else {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[↓]")}`);
				}
			}
		}

		updateHint();

		const container = new Container();
		container.addChild(border);
		container.addChild(new Spacer(1));
		container.addChild(contentText);
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				contentText.setText(renderDrillDownContent(draft, item, theme).join("\n"));
				const lines = container.render(width);
				if (editorFocused) {
					// Insert editor lines after feedback label
					const editorLines = editor.render(width - 2);
					const labelIdx = lines.findIndex((l) => l.includes("Feedback"));
					if (labelIdx >= 0) {
						lines.splice(labelIdx + 1, 0, ...editorLines);
					}
				}
				return lines;
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (editorFocused) {
					// Editor mode
					if (matchesKey(data, "escape")) {
						if (editor.getText() !== "") {
							editor.setText("");
						} else {
							editorFocused = false;
							editor.focused = false;
							updateHint();
						}
						container.invalidate();
					} else if ((data === "\x1b[A" || data === "\x7f" || data === "\b") && editor.getText() === "") {
						// Up or backspace on empty: unfocus
						editorFocused = false;
						editor.focused = false;
						updateHint();
						container.invalidate();
					} else {
						editor.handleInput(data);
						container.invalidate();
					}
				} else {
					// Content mode — hotkeys active
					if (matchesKey(data, "escape")) {
						// Save any pending feedback before leaving
						done("back");
					} else if (data === "a" || data === "A") {
						done("approve");
					} else if (data === "r" || data === "R") {
						done("revise");
					} else if (data === "\x1b[B" || matchesKey(data, "tab")) {
						// Down or Tab: focus editor, pre-populate with existing feedback
						editorFocused = true;
						editor.focused = true;
						const existingFb = getItemReview(draft, item).feedback ?? "";
						editor.setText(existingFb);
						updateHint();
						container.invalidate();
					}
				}
			},
		};
	});

	if (action === "approve") {
		const current = getItemReview(draft, item);
		setItemReview(draft, item, { approved: true, feedback: current.feedback });
	} else if (action === "revise") {
		const current = getItemReview(draft, item);
		setItemReview(draft, item, { approved: false, feedback: current.feedback });
	}
}

// ============================================================================
// Task card viewer — browse tasks with prev/next, collective approve/revise
// ============================================================================

async function showTaskCards(draft: PlanDraft, ctx: ExtensionContext): Promise<void> {
	const tasks = draft.tasks;
	if (tasks.length === 0) return;

	const action = await ctx.ui.custom<"approve" | "revise" | "back">((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text("", 1, 0);
		const contentText = new Text("", 0, 0);
		const feedbackLabel = new Text("", 0, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const editor = new Editor(tui, editorTheme, { paddingX: 0 });
		const currentFeedback = draft.tasksReview.feedback ?? "";
		editor.setText(currentFeedback);
		editor.focused = false;

		let currentIdx = 0;
		let editorFocused = false;

		editor.onSubmit = (value: string) => {
			const trimmed = value.trim();
			draft.tasksReview = { approved: draft.tasksReview.approved, feedback: trimmed || null };
			editorFocused = false;
			editor.focused = false;
			updateHint();
			container.invalidate();
		};

		function updateHint(): void {
			if (editorFocused) {
				hint.setText(theme.fg("dim", "[Enter: Save]  [Esc: Clear/Back]"));
				feedbackLabel.setText(theme.fg("accent", "Feedback"));
			} else {
				const parts = ["[←→: Navigate]", "[a: Approve all]", "[r: Revise all]", "[↓: Feedback]", "[Esc: Back]"];
				hint.setText(theme.fg("dim", parts.join("  ")));
				const fb = draft.tasksReview.feedback;
				if (fb) {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}\n${fb}`);
				} else {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[↓]")}`);
				}
			}
		}

		function renderCard(): string[] {
			const task = tasks[currentIdx]!;
			const lines: string[] = [];
			const idx = theme.fg("dim", `[${currentIdx}]`);
			lines.push(`${idx} ${theme.fg("accent", theme.bold(task.label))}`);
			lines.push("");
			lines.push(`${theme.fg("dim", "Description")}  ${task.description}`);
			lines.push("");
			lines.push(`${theme.fg("dim", "Criteria")}  ${task.criteria}`);
			return lines;
		}

		updateHint();

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(contentText);
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const marker = reviewMarker(draft.tasksReview, theme);
				header.setText(
					`${marker} ${theme.fg("accent", theme.bold("Tasks"))}  ${theme.fg("dim", `${currentIdx + 1} of ${tasks.length}`)}`,
				);
				contentText.setText(renderCard().join("\n"));
				const lines = container.render(width);
				if (editorFocused) {
					const editorLines = editor.render(width - 2);
					const labelIdx = lines.findIndex((l) => l.includes("Feedback"));
					if (labelIdx >= 0) {
						lines.splice(labelIdx + 1, 0, ...editorLines);
					}
				}
				return lines;
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (editorFocused) {
					if (matchesKey(data, "escape")) {
						if (editor.getText() !== "") {
							editor.setText("");
						} else {
							editorFocused = false;
							editor.focused = false;
							updateHint();
						}
						container.invalidate();
					} else if ((data === "\x1b[A" || data === "\x7f" || data === "\b") && editor.getText() === "") {
						editorFocused = false;
						editor.focused = false;
						updateHint();
						container.invalidate();
					} else {
						editor.handleInput(data);
						container.invalidate();
					}
				} else {
					if (matchesKey(data, "escape")) {
						done("back");
					} else if (data === "a" || data === "A") {
						done("approve");
					} else if (data === "r" || data === "R") {
						done("revise");
					} else if (matchesKey(data, "left")) {
						if (currentIdx > 0) {
							currentIdx--;
							container.invalidate();
						}
					} else if (matchesKey(data, "right")) {
						if (currentIdx < tasks.length - 1) {
							currentIdx++;
							container.invalidate();
						}
					} else if (data === "\x1b[B" || matchesKey(data, "tab")) {
						editorFocused = true;
						editor.focused = true;
						const existingFb = draft.tasksReview.feedback ?? "";
						editor.setText(existingFb);
						updateHint();
						container.invalidate();
					}
				}
			},
		};
	});

	if (action === "approve") {
		draft.tasksReview = { approved: true, feedback: draft.tasksReview.feedback };
	} else if (action === "revise") {
		draft.tasksReview = { approved: false, feedback: draft.tasksReview.feedback };
	}
}

// ============================================================================
// Read-only plan view
// ============================================================================

export async function showPlanReadOnly(planRef: GoalCycle["planRef"], ctx: ExtensionContext): Promise<void> {
	if (!planRef) return;

	await ctx.ui.custom<void>((_tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const content = new Text("", 0, 0);
		const hint = new Text(theme.fg("dim", "Esc close"), 1, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(new Text(theme.fg("accent", theme.bold("Plan (approved)")), 1, 0));
		container.addChild(new Spacer(1));
		container.addChild(content);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const lines: string[] = [];
				for (const name of ["context", "design", "success", "boundaries"] as const) {
					lines.push(theme.fg("accent", theme.bold(sectionDisplayName(name))));
					lines.push(planRef[name]);
					lines.push("");
				}
				content.setText(lines.join("\n"));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape")) done(undefined);
			},
		};
	});
}
