import type { WorktreeSetupResult } from "#core/project/workspace/setup.ts";
import type { WorkstreamDetail, WorkstreamSummary } from "#core/swarm/agents/client.ts";

export interface CreateWorkstreamResultDetails {
	status: "created" | "failed";
	message: string;
	id?: string;
	slug?: string;
	next_step: string;
}

export interface EditWorkstreamResultDetails {
	status: "edited" | "not_found" | "failed";
	message: string;
	id?: string;
	slug?: string;
	version?: number | null;
	next_step: string;
}

export interface LaunchWorkstreamResultDetails {
	status: "launched" | "failed";
	message: string;
	id?: string;
	slug?: string;
	worktree?: {
		label: string;
		path?: string;
		branch?: string | null;
		created?: boolean;
	};
	setup_summary?: WorktreeSetupResult | { status: string; message: string };
	herdr_summary?: unknown;
	next_step: string;
}

export interface ListWorkstreamsResultDetails {
	status: "ok" | "failed";
	message: string;
	count: number;
	workstreams: WorkstreamSummary[];
	workstream?: WorkstreamDetail;
	next_step: string;
}

export interface SetWorkstreamStatusResultDetails {
	status: "updated" | "not_found" | "invalid_status" | "failed";
	message: string;
	workstream: string;
	next_step: string;
}

export type ToolResult<T> = {
	content: { type: "text"; text: string }[];
	details: T;
	isError?: boolean;
};

export type CreateWorkstreamToolResult = ToolResult<CreateWorkstreamResultDetails>;
export type EditWorkstreamToolResult = ToolResult<EditWorkstreamResultDetails>;
export type LaunchWorkstreamToolResult = ToolResult<LaunchWorkstreamResultDetails>;
export type ListWorkstreamsToolResult = ToolResult<ListWorkstreamsResultDetails>;
export type SetWorkstreamStatusToolResult = ToolResult<SetWorkstreamStatusResultDetails>;

function toolResult<T>(details: T, isError = false): ToolResult<T> {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

export function createTextResult(details: CreateWorkstreamResultDetails, isError = false): CreateWorkstreamToolResult {
	return toolResult(details, isError);
}

export function editTextResult(details: EditWorkstreamResultDetails, isError = false): EditWorkstreamToolResult {
	return toolResult(details, isError);
}

export function launchTextResult(details: LaunchWorkstreamResultDetails, isError = false): LaunchWorkstreamToolResult {
	return toolResult(details, isError);
}

export function listTextResult(details: ListWorkstreamsResultDetails, isError = false): ListWorkstreamsToolResult {
	return toolResult(details, isError);
}

export function statusTextResult(
	details: SetWorkstreamStatusResultDetails,
	isError = false,
): SetWorkstreamStatusToolResult {
	return toolResult(details, isError);
}

export function failedCreateDetails(message: string, nextStep: string): CreateWorkstreamResultDetails {
	return { status: "failed", message, next_step: nextStep };
}

export function failedLaunchDetails(message: string, nextStep: string): LaunchWorkstreamResultDetails {
	return { status: "failed", message, next_step: nextStep };
}
