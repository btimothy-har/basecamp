export interface PlanTaskInput {
	label: string;
	description: string;
	criteria: string;
}

export interface PlanWorkstreamInput {
	id: string;
	label: string;
	scope: string;
	outcome: string;
	boundaries: string;
	worktreeSlug?: string;
	dependsOn?: string[];
}

export type NormalizedPlanExecutionInput =
	| { kind: "tasks"; tasks: PlanTaskInput[] }
	| { kind: "workstreams"; workstreams: PlanWorkstreamInput[] };

function hasOwnObjectKey(value: object, key: string): boolean {
	return Object.hasOwn(value, key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertNonEmptyArray(value: unknown, field: "tasks" | "workstreams"): asserts value is unknown[] {
	if (!Array.isArray(value)) {
		throw new Error(`plan() requires '${field}' to be an array.`);
	}
	if (value.length === 0) {
		throw new Error(`plan() requires '${field}' to contain at least one item.`);
	}
}

function validateWorkstream(workstream: unknown, index: number): PlanWorkstreamInput {
	if (!isRecord(workstream)) {
		throw new Error(`plan() workstream at index ${index} must be an object.`);
	}
	if (hasOwnObjectKey(workstream, "tasks")) {
		throw new Error("plan() workstreams must not contain nested 'tasks'.");
	}

	for (const field of ["id", "label", "scope", "outcome", "boundaries"] as const) {
		if (typeof workstream[field] !== "string") {
			throw new Error(`plan() workstream at index ${index} requires string '${field}'.`);
		}
	}
	const { id, label, scope, outcome, boundaries } = workstream as Record<
		"id" | "label" | "scope" | "outcome" | "boundaries",
		string
	>;

	let worktreeSlug: string | undefined;
	if (hasOwnObjectKey(workstream, "worktreeSlug")) {
		if (typeof workstream.worktreeSlug !== "string") {
			throw new Error(`plan() workstream at index ${index} requires string 'worktreeSlug' when provided.`);
		}
		worktreeSlug = workstream.worktreeSlug;
	}

	let dependsOn: string[] | undefined;
	if (hasOwnObjectKey(workstream, "dependsOn")) {
		if (!Array.isArray(workstream.dependsOn)) {
			throw new Error(`plan() workstream at index ${index} requires 'dependsOn' to be an array when provided.`);
		}
		dependsOn = workstream.dependsOn.map((dependency) => {
			if (typeof dependency !== "string") {
				throw new Error(`plan() workstream at index ${index} requires string dependency ids in 'dependsOn'.`);
			}
			return dependency.trim();
		});
	}

	return {
		id: id.trim(),
		label,
		scope,
		outcome,
		boundaries,
		...(worktreeSlug !== undefined ? { worktreeSlug } : {}),
		...(dependsOn !== undefined ? { dependsOn } : {}),
	};
}

export function normalizePlanExecutionInput(input: unknown): NormalizedPlanExecutionInput {
	if (!isRecord(input)) {
		throw new Error("plan() input must be an object.");
	}

	const hasTasks = hasOwnObjectKey(input, "tasks");
	const hasWorkstreams = hasOwnObjectKey(input, "workstreams");

	if (hasTasks && hasWorkstreams) {
		throw new Error("plan() accepts either 'tasks' or 'workstreams', not both.");
	}
	if (!hasTasks && !hasWorkstreams) {
		throw new Error("plan() requires either 'tasks' or 'workstreams'.");
	}

	if (hasTasks) {
		assertNonEmptyArray(input.tasks, "tasks");
		return { kind: "tasks", tasks: input.tasks as PlanTaskInput[] };
	}

	assertNonEmptyArray(input.workstreams, "workstreams");
	const workstreams = input.workstreams.map(validateWorkstream);
	const ids = new Set<string>();
	for (const workstream of workstreams) {
		const id = workstream.id;
		if (!id) {
			throw new Error("plan() workstream ids must not be empty.");
		}
		if (ids.has(id)) {
			throw new Error(`plan() workstream id '${id}' is duplicated.`);
		}
		ids.add(id);
	}
	for (const workstream of workstreams) {
		for (const dependencyId of workstream.dependsOn ?? []) {
			if (!dependencyId) {
				throw new Error(`plan() workstream '${workstream.id}' has an empty dependency id.`);
			}
			if (!ids.has(dependencyId)) {
				throw new Error(`plan() workstream '${workstream.id}' depends on unknown workstream '${dependencyId}'.`);
			}
		}
	}

	return { kind: "workstreams", workstreams };
}
