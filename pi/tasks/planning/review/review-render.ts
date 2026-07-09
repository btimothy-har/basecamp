/** Text rendering for the plan-review list and drill-down views. */

import type { Theme } from "@earendil-works/pi-coding-agent";
import { deriveGoalContextReviewState } from "../draft/draft-logic.ts";
import { type PlanDraft, type ReviewItem, reviewMarker, sectionDisplayName } from "./review-model.ts";

export function renderListView(items: ReviewItem[], selected: number, draft: PlanDraft, theme: Theme): string[] {
	const lines: string[] = [];

	for (let i = 0; i < items.length; i++) {
		const item = items[i]!;
		const cursor = i === selected ? theme.fg("accent", "▸") : " ";

		if (item.kind === "goalContext") {
			const marker = reviewMarker(deriveGoalContextReviewState(draft), theme);
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

export function renderDrillDownContent(draft: PlanDraft, item: ReviewItem, theme: Theme): string[] {
	const lines: string[] = [];

	if (item.kind === "goalContext") {
		const marker = reviewMarker(deriveGoalContextReviewState(draft), theme);
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
