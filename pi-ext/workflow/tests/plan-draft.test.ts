import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	computeGoalContextReview,
	computeSectionReview,
	type DraftGoalContext,
	deriveGoalContextReviewState,
	freshReview,
	type PlanSection,
	type TaskInput,
	tasksMatch,
} from "../src/planning/draft-logic.ts";

function approvedSection(content: string): PlanSection {
	return { content, review: { approved: true, feedback: null } };
}

function pendingSection(content: string): PlanSection {
	return { content, review: { approved: null, feedback: null } };
}

function rejectedSection(content: string, feedback: string | null = null): PlanSection {
	return { content, review: { approved: false, feedback } };
}

describe("computeGoalContextReview — coupled preservation", () => {
	it("context-only change invalidates both", () => {
		const previous: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("Goal", "Changed context", previous);

		assert.equal(review.approved, null, "should be pending when context changes");
	});

	it("goal-only change invalidates both", () => {
		const previous: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("Changed goal", "Context", previous);

		assert.equal(review.approved, null, "should be pending when goal changes");
	});

	it("unchanged pair preserves approval when both were approved", () => {
		const previous: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("Goal", "Context", previous);

		assert.equal(review.approved, true, "should remain approved when nothing changes");
	});

	it("approval not preserved when previous goal was not approved", () => {
		const previous: DraftGoalContext = {
			goal: pendingSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("Goal", "Context", previous);

		assert.equal(review.approved, null, "should be pending because previous goal wasn't approved");
	});

	it("approval not preserved when previous context was not approved", () => {
		const previous: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: pendingSection("Context"),
		};

		const review = computeGoalContextReview("Goal", "Context", previous);

		assert.equal(review.approved, null, "should be pending because previous context wasn't approved");
	});

	it("approval not preserved when previous goal was rejected", () => {
		const previous: DraftGoalContext = {
			goal: rejectedSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("Goal", "Context", previous);

		assert.equal(review.approved, null, "should be pending because previous goal was rejected");
	});

	it("no previous draft starts as pending", () => {
		const review = computeGoalContextReview("Goal", "Context", null);

		assert.equal(review.approved, null, "should be pending with no previous draft");
	});

	it("both changed resets to pending", () => {
		const previous: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: approvedSection("Context"),
		};

		const review = computeGoalContextReview("New goal", "New context", previous);

		assert.equal(review.approved, null, "should be pending when both change");
	});
});

describe("deriveGoalContextReviewState — combined display state", () => {
	it("returns approved when both goal and context are approved", () => {
		const draft: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: approvedSection("Context"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, true);
	});

	it("returns pending when goal is pending", () => {
		const draft: DraftGoalContext = {
			goal: pendingSection("Goal"),
			context: approvedSection("Context"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, null);
	});

	it("returns pending when context is pending", () => {
		const draft: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: pendingSection("Context"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, null);
	});

	it("returns rejected when goal is rejected", () => {
		const draft: DraftGoalContext = {
			goal: rejectedSection("Goal", "Needs work"),
			context: approvedSection("Context"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, false);
		assert.equal(state.feedback, "Needs work");
	});

	it("returns rejected when context is rejected", () => {
		const draft: DraftGoalContext = {
			goal: approvedSection("Goal"),
			context: rejectedSection("Context", "Missing info"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, false);
		assert.equal(state.feedback, "Missing info");
	});

	it("prefers goal feedback when both have feedback", () => {
		const draft: DraftGoalContext = {
			goal: { content: "Goal", review: { approved: true, feedback: "Goal note" } },
			context: { content: "Context", review: { approved: true, feedback: "Context note" } },
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.feedback, "Goal note");
	});

	it("falls back to context feedback when goal has none", () => {
		const draft: DraftGoalContext = {
			goal: { content: "Goal", review: { approved: true, feedback: null } },
			context: { content: "Context", review: { approved: true, feedback: "Context note" } },
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.feedback, "Context note");
	});

	it("pending takes priority over rejected", () => {
		const draft: DraftGoalContext = {
			goal: pendingSection("Goal"),
			context: rejectedSection("Context"),
		};

		const state = deriveGoalContextReviewState(draft);
		assert.equal(state.approved, null, "pending should take priority");
	});
});

describe("computeSectionReview — independent sections", () => {
	it("unchanged content preserves approval", () => {
		const previous = approvedSection("Design content");

		const review = computeSectionReview("Design content", previous);

		assert.equal(review.approved, true);
	});

	it("changed content resets to pending", () => {
		const previous = approvedSection("Design content");

		const review = computeSectionReview("Changed design", previous);

		assert.equal(review.approved, null);
	});

	it("no previous section starts as pending", () => {
		const review = computeSectionReview("New design", null);

		assert.equal(review.approved, null);
	});

	it("unchanged content with pending previous stays pending", () => {
		const previous = pendingSection("Design content");

		const review = computeSectionReview("Design content", previous);

		assert.equal(review.approved, null);
	});
});

describe("tasksMatch", () => {
	it("returns true for identical tasks", () => {
		const tasks: TaskInput[] = [
			{ label: "Task 1", description: "Do A", criteria: "A done" },
			{ label: "Task 2", description: "Do B", criteria: "B done" },
		];
		const previous: TaskInput[] = [
			{ label: "Task 1", description: "Do A", criteria: "A done" },
			{ label: "Task 2", description: "Do B", criteria: "B done" },
		];

		assert.equal(tasksMatch(tasks, previous), true);
	});

	it("returns false when task count differs", () => {
		const tasks: TaskInput[] = [{ label: "Task 1", description: "Do A", criteria: "A done" }];
		const previous: TaskInput[] = [
			{ label: "Task 1", description: "Do A", criteria: "A done" },
			{ label: "Task 2", description: "Do B", criteria: "B done" },
		];

		assert.equal(tasksMatch(tasks, previous), false);
	});

	it("returns false when label differs", () => {
		const tasks: TaskInput[] = [{ label: "Changed", description: "Do A", criteria: "A done" }];
		const previous: TaskInput[] = [{ label: "Task 1", description: "Do A", criteria: "A done" }];

		assert.equal(tasksMatch(tasks, previous), false);
	});

	it("returns false when description differs", () => {
		const tasks: TaskInput[] = [{ label: "Task 1", description: "Changed", criteria: "A done" }];
		const previous: TaskInput[] = [{ label: "Task 1", description: "Do A", criteria: "A done" }];

		assert.equal(tasksMatch(tasks, previous), false);
	});

	it("returns false when criteria differs", () => {
		const tasks: TaskInput[] = [{ label: "Task 1", description: "Do A", criteria: "Changed" }];
		const previous: TaskInput[] = [{ label: "Task 1", description: "Do A", criteria: "A done" }];

		assert.equal(tasksMatch(tasks, previous), false);
	});

	it("returns true for empty task lists", () => {
		assert.equal(tasksMatch([], []), true);
	});
});

describe("freshReview", () => {
	it("returns pending state", () => {
		const review = freshReview();
		assert.equal(review.approved, null);
		assert.equal(review.feedback, null);
	});
});
