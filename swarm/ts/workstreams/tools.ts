/**
 * Workstream tool registration — composition over deps/params/results,
 * provision, launch/, list, and status modules.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { defaultWorkstreamToolsDeps } from "./deps.ts";
import { executeLaunchWorkstream } from "./launch/execute.ts";
import { executeListWorkstreams } from "./list.ts";
import { executeSetWorkstreamStatus } from "./status.ts";

export type { WorkstreamToolsDeps } from "./deps.ts";
export { defaultWorkstreamToolsDeps } from "./deps.ts";
export { executeLaunchWorkstream } from "./launch/execute.ts";
export { executeListWorkstreams } from "./list.ts";
export type { LaunchWorkstreamParams, ListWorkstreamsParams, SetWorkstreamStatusParams } from "./params.ts";
export { parseLaunchWorkstreamParams } from "./params.ts";
export type {
	LaunchWorkstreamResultDetails,
	ListWorkstreamsResultDetails,
	SetWorkstreamStatusResultDetails,
} from "./results.ts";
export { executeSetWorkstreamStatus } from "./status.ts";

export function registerWorkstreamTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<unknown>,
	_deps?: import("./deps.ts").WorkstreamToolsDeps,
): void {
	const deps = _deps ?? defaultWorkstreamToolsDeps(getConnection);

	pi.registerTool({
		name: "launch_workstream",
		label: "Launch Workstream",
		description:
			"Stage a workstream from a dossier brief: provision one generically-named worktree (copilot/<three-words>), open a Herdr pane on it, and create the workstream in the daemon. Pass an existing workstream id or slug to carry it into the current repo (reuses the worktree idempotently). The user runs `pi --workstream=<slug>` in that pane to start the agent.",
		promptSnippet: "Stage or carry a Herdr workstream worktree + pane",
		parameters: Type.Object(
			{
				source: Type.Object(
					{
						dossierPath: Type.String({ description: "Path to the dossier that defines the launch context." }),
						repoPagePath: Type.Optional(
							Type.String({ description: "Optional path to the repository cockpit/page for additional context." }),
						),
					},
					{ additionalProperties: false },
				),
				workstream: Type.Object(
					{
						label: Type.String({
							description: "Human-readable workstream label (used in the brief).",
						}),
						brief: Type.String({
							description: "Workstream brief the launched agent will receive via pi --workstream.",
						}),
						constraints: Type.Optional(Type.String({ description: "Optional constraints for the workstream." })),
						worktreeSlug: Type.Optional(
							Type.String({
								description:
									"Optional slug used to derive the initial bt/ branch name (the worktree itself gets a generic name).",
							}),
						),
					},
					{ additionalProperties: false },
				),
				workstream_id: Type.Optional(
					Type.String({
						description:
							"Optional existing workstream id or slug to carry into the current repo. When omitted, a new workstream is created.",
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
			"List workstreams from the daemon. Filters by repo, dossierPath, query (slug/label substring), and status (open|closed). For a single-identifier lookup (query only), returns the workstream detail with the joined agents view.",
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
