import type { ReviewState } from "../tasks/tasks";

export interface PlanSection {
	content: string;
	review: ReviewState;
}

export interface TaskInput {
	label: string;
	description: string;
	criteria: string;
}

export interface DraftGoalContext {
	goal: PlanSection;
	context: PlanSection;
}

export function freshReview(): ReviewState {
	return { approved: null, feedback: null };
}

export function computeGoalContextReview(
	goalContent: string,
	contextContent: string,
	previous: DraftGoalContext | null,
): ReviewState {
	if (!previous) return freshReview();

	const goalUnchanged = previous.goal.content === goalContent;
	const contextUnchanged = previous.context.content === contextContent;
	const goalApproved = previous.goal.review.approved === true;
	const contextApproved = previous.context.review.approved === true;

	if (goalUnchanged && contextUnchanged && goalApproved && contextApproved) {
		return { approved: true, feedback: null };
	}

	return freshReview();
}

export function deriveGoalContextReviewState(draft: DraftGoalContext): ReviewState {
	const goalReview = draft.goal.review;
	const contextReview = draft.context.review;
	const feedback = goalReview.feedback ?? contextReview.feedback;

	if (goalReview.approved === null || contextReview.approved === null) {
		return { approved: null, feedback };
	}

	if (goalReview.approved === false || contextReview.approved === false) {
		return { approved: false, feedback };
	}

	return { approved: true, feedback };
}

export function tasksMatch(tasks: TaskInput[], previousTasks: TaskInput[]): boolean {
	if (tasks.length !== previousTasks.length) return false;
	for (let i = 0; i < tasks.length; i++) {
		const curr = tasks[i]!;
		const prev = previousTasks[i]!;
		if (curr.label !== prev.label || curr.description !== prev.description || curr.criteria !== prev.criteria) {
			return false;
		}
	}
	return true;
}

export function computeSectionReview(content: string, previousSection: PlanSection | null): ReviewState {
	if (!previousSection) return freshReview();
	if (previousSection.content === content && previousSection.review.approved === true) {
		return { approved: true, feedback: null };
	}
	return freshReview();
}
