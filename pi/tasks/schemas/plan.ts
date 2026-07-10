/**
 * Plan-domain data models — the shared shape of a plan draft and its sections.
 *
 * Consumed by the workflows layer (draft/review/handoff) and the plan tool.
 * Review-view helpers (markers, list items) live in workflows/review, not here.
 */

import type { ReviewState, Task } from "./task.ts";

export interface PlanSection {
	content: string;
	review: ReviewState;
}

export const SECTION_NAMES = ["goal", "context", "design", "success", "boundaries"] as const;
export type SectionName = (typeof SECTION_NAMES)[number];

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

export type ImplementationMode = "supervisor" | "executor";
