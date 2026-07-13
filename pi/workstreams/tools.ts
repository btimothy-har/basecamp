/**
 * Workstream tool registration — composition over deps/params/results and the
 * per-verb executors: create (record), edit (revise), launch (worktree + pane),
 * list, and status.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { executeCreateWorkstream } from "./create.ts";
import { defaultWorkstreamToolsDeps } from "./deps.ts";
import { executeEditWorkstream } from "./edit.ts";
import { executeLaunchWorkstream } from "./launch.ts";
import { executeListWorkstreams } from "./list.ts";
import { executeSetWorkstreamStatus } from "./status.ts";

export { executeCreateWorkstream } from "./create.ts";
export type { WorkstreamToolsDeps } from "./deps.ts";
export { defaultWorkstreamToolsDeps } from "./deps.ts";
export { executeEditWorkstream } from "./edit.ts";
export { executeLaunchWorkstream } from "./launch.ts";
export { executeListWorkstreams } from "./list.ts";
export type {
	CreateWorkstreamParams,
	EditWorkstreamParams,
	LaunchWorkstreamParams,
	ListWorkstreamsParams,
	SetWorkstreamStatusParams,
} from "./params.ts";
export type {
	CreateWorkstreamResultDetails,
	EditWorkstreamResultDetails,
	LaunchWorkstreamResultDetails,
	ListWorkstreamsResultDetails,
	SetWorkstreamStatusResultDetails,
} from "./results.ts";
export { executeSetWorkstreamStatus } from "./status.ts";

const sourceSchema = Type.Object(
	{
		dossierPath: Type.String({ description: "Path to the dossier that defines the workstream context." }),
		repoPagePath: Type.Optional(
			Type.String({ description: "Optional path to the repository cockpit/page for additional context." }),
		),
	},
	{ additionalProperties: false },
);

export function registerWorkstreamTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<unknown>,
	_deps?: import("./deps.ts").WorkstreamToolsDeps,
): void {
	const deps = _deps ?? defaultWorkstreamToolsDeps(getConnection);

	pi.registerTool({
		name: "create_workstream",
		label: "Create Workstream",
		description:
			"Create a durable workstream record in the daemon from a dossier brief (label, brief, optional constraints). Returns its internal id and readable three-word slug. Record-only: it does not provision a worktree, open a Herdr pane, or start an agent — use launch_workstream to stage execution.",
		promptSnippet: "Create a durable workstream record",
		parameters: Type.Object(
			{
				source: sourceSchema,
				workstream: Type.Object(
					{
						label: Type.String({ description: "Human-readable workstream label (used in the brief)." }),
						brief: Type.String({
							description: "Workstream brief the launched agent will receive via pi --workstream.",
						}),
						constraints: Type.Optional(Type.String({ description: "Optional constraints for the workstream." })),
					},
					{ additionalProperties: false },
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeCreateWorkstream(params, deps);
		},
	});

	pi.registerTool({
		name: "edit_workstream",
		label: "Edit Workstream",
		description:
			"Revise an existing workstream's content (any of label, brief, constraints) in place, bumping its version and keeping the old version. Identity (id/slug), dossier pointer, worktree, and attached agents are unchanged. Record-only. Unspecified fields carry forward from the current version.",
		promptSnippet: "Revise a workstream (keeps old version)",
		parameters: Type.Object(
			{
				workstream: Type.String({ description: "Workstream id or slug to revise." }),
				label: Type.Optional(Type.String({ description: "New label. Omit to keep the current label." })),
				brief: Type.Optional(Type.String({ description: "New brief. Omit to keep the current brief." })),
				constraints: Type.Optional(
					Type.String({
						description:
							"New constraints text. Omit to keep the current constraints; constraints cannot be cleared, so to record that they changed pass explicit text (e.g. 'None').",
					}),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeEditWorkstream(params, deps);
		},
	});

	pi.registerTool({
		name: "launch_workstream",
		label: "Launch Workstream",
		description:
			"Stage execution for an existing workstream: provision its copilot/<slug> worktree (idempotent) and open a Herdr pane on it. Resolves the workstream by id or slug — create it first with create_workstream. Carries the workstream into the current repo. The user runs `pi --workstream` in that pane to start the agent.",
		promptSnippet: "Provision a Herdr workstream worktree + pane",
		parameters: Type.Object(
			{
				workstream: Type.String({ description: "Existing workstream id or slug to launch in the current repo." }),
				worktreeSlug: Type.Optional(
					Type.String({
						description:
							"Optional slug used to derive the initial bt/ branch name (the worktree keeps its generic copilot/<slug> name).",
					}),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params, signal, _onUpdate, ctx) {
			return await executeLaunchWorkstream(params, pi, ctx, signal, deps);
		},
	});

	pi.registerTool({
		name: "list_workstreams",
		label: "List Workstreams",
		description:
			"List workstreams from the daemon. Filters by repo, dossierPath, query (slug/label substring), and status (open|closed). For a single-identifier lookup (query only), returns the workstream detail with the joined agents view and version history.",
		promptSnippet: "List workstreams from the daemon",
		parameters: Type.Object(
			{
				repo: Type.Optional(Type.String({ description: "Filter to workstreams with agents in this repo." })),
				dossierPath: Type.Optional(Type.String({ description: "Filter to workstreams from this dossier path." })),
				query: Type.Optional(
					Type.String({
						description:
							"Case-insensitive substring filter for slug or label. When used alone, returns the workstream detail with agents.",
					}),
				),
				slug: Type.Optional(Type.String({ description: "Alias for query." })),
				label: Type.Optional(Type.String({ description: "Alias for query." })),
				status: Type.Optional(
					Type.Union([Type.Literal("open"), Type.Literal("closed")], {
						description: "Filter by workstream status.",
					}),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeListWorkstreams(params, deps);
		},
	});

	pi.registerTool({
		name: "set_workstream_status",
		label: "Set Workstream Status",
		description: "Set the status of a workstream to 'open' or 'closed' via the daemon.",
		promptSnippet: "Open or close a workstream",
		parameters: Type.Object(
			{
				workstream: Type.String({ description: "Workstream id or slug." }),
				status: Type.Union([Type.Literal("open"), Type.Literal("closed")], {
					description: "New status for the workstream.",
				}),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeSetWorkstreamStatus(params, deps);
		},
	});
}
