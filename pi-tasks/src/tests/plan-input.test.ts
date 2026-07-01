import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { normalizePlanExecutionInput } from "../planning/plan-input.ts";

const basePlan = {
	goal: "Goal",
	context: "Context",
	design: "Design",
	success: "Success",
	boundaries: "Boundaries",
};

describe("normalizePlanExecutionInput", () => {
	it("accepts a valid task plan and preserves task objects", () => {
		const task = { label: " Task 1 ", description: " Do A ", criteria: " A done " };
		const result = normalizePlanExecutionInput({ ...basePlan, tasks: [task] });

		assert.equal(result.kind, "tasks");
		assert.deepEqual(result.tasks, [task]);
		assert.equal(result.tasks[0], task);
	});

	it("accepts a valid workstream plan and normalizes ids", () => {
		const result = normalizePlanExecutionInput({
			...basePlan,
			workstreams: [
				{
					id: "a",
					label: "Workstream A",
					scope: "Build A",
					outcome: "A works",
					boundaries: "Do not build B",
					worktreeSlug: "workstream-a",
				},
				{
					id: " b ",
					label: "Workstream B",
					scope: "Build B",
					outcome: "B works",
					boundaries: "Do not build C",
					dependsOn: [" a "],
				},
			],
		});

		assert.equal(result.kind, "workstreams");
		assert.deepEqual(result.workstreams, [
			{
				id: "a",
				label: "Workstream A",
				scope: "Build A",
				outcome: "A works",
				boundaries: "Do not build B",
				worktreeSlug: "workstream-a",
			},
			{
				id: "b",
				label: "Workstream B",
				scope: "Build B",
				outcome: "B works",
				boundaries: "Do not build C",
				dependsOn: ["a"],
			},
		]);
	});

	it("rejects a plan with both tasks and workstreams", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					tasks: [{ label: "Task", description: "Do it", criteria: "Done" }],
					workstreams: [{ id: "a", label: "A", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries" }],
				}),
			/either 'tasks' or 'workstreams', not both/,
		);
	});

	it("rejects a plan with neither tasks nor workstreams", () => {
		assert.throws(() => normalizePlanExecutionInput(basePlan), /requires either 'tasks' or 'workstreams'/);
	});

	it("rejects an empty tasks array", () => {
		assert.throws(
			() => normalizePlanExecutionInput({ ...basePlan, tasks: [] }),
			/'tasks' to contain at least one item/,
		);
	});

	it("rejects an empty workstreams array", () => {
		assert.throws(
			() => normalizePlanExecutionInput({ ...basePlan, workstreams: [] }),
			/'workstreams' to contain at least one item/,
		);
	});

	it("rejects duplicate workstream ids after trimming", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					workstreams: [
						{ id: "a", label: "A", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries" },
						{ id: " a ", label: "B", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries" },
					],
				}),
			/workstream id 'a' is duplicated/,
		);
	});

	it("rejects dependsOn references to unknown workstream ids after trimming", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					workstreams: [
						{
							id: "a",
							label: "A",
							scope: "Scope",
							outcome: "Outcome",
							boundaries: "Boundaries",
							dependsOn: [" missing "],
						},
					],
				}),
			/depends on unknown workstream 'missing'/,
		);
	});

	it("rejects workstream self-dependencies", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					workstreams: [
						{
							id: "a",
							label: "A",
							scope: "Scope",
							outcome: "Outcome",
							boundaries: "Boundaries",
							dependsOn: [" a "],
						},
					],
				}),
			/workstream 'a' must not depend on itself/,
		);
	});

	it("rejects workstream dependency cycles", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					workstreams: [
						{ id: "a", label: "A", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries", dependsOn: ["b"] },
						{ id: "b", label: "B", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries", dependsOn: ["c"] },
						{ id: "c", label: "C", scope: "Scope", outcome: "Outcome", boundaries: "Boundaries", dependsOn: ["a"] },
					],
				}),
			/dependency cycle detected: a -> b -> c -> a/,
		);
	});

	it("rejects nested tasks on a workstream", () => {
		assert.throws(
			() =>
				normalizePlanExecutionInput({
					...basePlan,
					workstreams: [
						{
							id: "a",
							label: "A",
							scope: "Scope",
							outcome: "Outcome",
							boundaries: "Boundaries",
							tasks: [{ label: "Nested", description: "No", criteria: "No" }],
						},
					],
				}),
			/must not contain nested 'tasks'/,
		);
	});
});
