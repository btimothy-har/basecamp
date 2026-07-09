import type { WorktreeSetupResult } from "#core/workspace/setup.ts";
import type { WorkstreamDetail, WorkstreamSummary } from "../agents/daemon/client.ts";

export interface LaunchWorkstreamResultDetails {
	status: "launched" | "carried" | "failed";
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

export type LaunchWorkstreamToolResult = {
	content: { type: "text"; text: string }[];
	details: LaunchWorkstreamResultDetails;
	isError?: boolean;
};

export interface ListWorkstreamsResultDetails {
	status: "ok" | "failed";
	message: string;
	count: number;
	workstreams: WorkstreamSummary[];
	workstream?: WorkstreamDetail;
	next_step: string;
}

export type ListWorkstreamsToolResult = {
	content: { type: "text"; text: string }[];
	details: ListWorkstreamsResultDetails;
	isError?: boolean;
};

export interface SetWorkstreamStatusResultDetails {
	status: "updated" | "not_found" | "invalid_status" | "failed";
	message: string;
	workstream: string;
	next_step: string;
}

export type SetWorkstreamStatusToolResult = {
	content: { type: "text"; text: string }[];
	details: SetWorkstreamStatusResultDetails;
	isError?: boolean;
};

export function textResult(details: LaunchWorkstreamResultDetails, isError = false): LaunchWorkstreamToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

export function listTextResult(details: ListWorkstreamsResultDetails, isError = false): ListWorkstreamsToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

export function statusTextResult(
	details: SetWorkstreamStatusResultDetails,
	isError = false,
): SetWorkstreamStatusToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

export function failedLaunchDetails(message: string, nextStep: string): LaunchWorkstreamResultDetails {
	return { status: "failed", message, next_step: nextStep };
}
