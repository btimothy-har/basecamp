/**
 * Review overlays — interactive TUI components for plan review.
 *
 * Three views:
 *   - List: browse review items, drill into any (here)
 *   - Drill-down: view content + feedback, approve/revise/edit (here)
 *   - Task cards: collective task review (task-cards.ts)
 *   - Read-only: shows approved plan (for /show-plan after approval)
 *
 * The PlanDraft model and review-item accessors live in review-model.ts;
 * list/drill-down text rendering in review-render.ts.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@earendil-works/pi-coding-agent";
import { Container, Editor, type EditorTheme, matchesKey, Spacer, Text } from "@earendil-works/pi-tui";
import type { PlanDraft } from "../../schemas/plan.ts";
import type { GoalCycle } from "../../schemas/task.ts";
import {
	countPending,
	getItemReview,
	getListItems,
	type ReviewItem,
	sectionDisplayName,
	setItemReview,
} from "./review-model.ts";
import { renderDrillDownContent, renderListView } from "./review-render.ts";
import { showTaskCards } from "./task-cards.ts";

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
					} else if (matchesKey(data, "s") || matchesKey(data, "shift+s")) {
						const pending = countPending(draft);
						if (pending > 0) {
							hint.setText(theme.fg("warning", `${pending} item${pending > 1 ? "s" : ""} still pending review`));
							container.invalidate();
							return;
						}
						done("submit");
					} else if (matchesKey(data, "space") || matchesKey(data, "enter")) {
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
					} else if ((matchesKey(data, "up") || matchesKey(data, "backspace")) && editor.getText() === "") {
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
					} else if (matchesKey(data, "a") || matchesKey(data, "shift+a")) {
						done("approve");
					} else if (matchesKey(data, "r") || matchesKey(data, "shift+r")) {
						done("revise");
					} else if (matchesKey(data, "down") || matchesKey(data, "tab")) {
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
