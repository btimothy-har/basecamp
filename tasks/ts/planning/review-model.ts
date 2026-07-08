/**
 * Plan-review model — the PlanDraft shape, review items, and per-item
 * review-state accessors shared by the review overlays.
 *
 * Goal + Context are merged into a single review item.
 * Design, Success, Boundaries are individual items.
 */

import type { Theme } from "@earendil-works/pi-coding-agent";
import type { ReviewState, Task } from "../tasks/tasks.ts";
import { deriveGoalContextReviewState } from "./draft-logic.ts";

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
	worktreeSlug: string | null;
	tasks: Task[];
	tasksReview: ReviewState;
}

export const SECTION_NAMES = ["goal", "context", "design", "success", "boundaries"] as const;
export type SectionName = (typeof SECTION_NAMES)[number];

/** Sections that appear as individual review items (not goal/context). */
export const INDIVIDUAL_SECTIONS: SectionName[] = ["design", "success", "boundaries"];

export type ReviewItem = { kind: "goalContext" } | { kind: "section"; name: SectionName } | { kind: "tasks" };

export function sectionDisplayName(name: SectionName): string {
	return name.charAt(0).toUpperCase() + name.slice(1);
}

export function reviewMarker(review: ReviewState, theme: Theme): string {
	let state: string;
	if (review.approved === true) state = theme.fg("success", "✓");
	else if (review.approved === false) state = theme.fg("warning", "★");
	else state = theme.fg("muted", "☐");

	const note = review.feedback ? theme.fg("dim", " 📝") : "";
	return `${state}${note}`;
}

export function countPending(draft: PlanDraft): number {
	let count = 0;
	if (deriveGoalContextReviewState(draft).approved === null) count++;
	for (const name of INDIVIDUAL_SECTIONS) {
		if (draft[name].review.approved === null) count++;
	}
	// Tasks are a single collective review item
	if (draft.tasksReview.approved === null) count++;
	return count;
}

export function getListItems(draft: PlanDraft): ReviewItem[] {
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

export function getItemReview(draft: PlanDraft, item: ReviewItem): ReviewState {
	if (item.kind === "goalContext") return deriveGoalContextReviewState(draft);
	if (item.kind === "section") return draft[item.name].review;
	return draft.tasksReview;
}

export function setItemReview(draft: PlanDraft, item: ReviewItem, review: ReviewState): void {
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
