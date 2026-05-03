import type { WorkspaceState } from "../../platform/workspace";

export interface UnsafeEditConstraints {
	readOnly: boolean;
	hasUI: boolean;
	isSubagent: boolean;
}

export type UnsafeEditFlagResult =
	| "disabled"
	| "enabled"
	| "ignored-read-only"
	| "ignored-subagent"
	| "ignored-non-interactive";

export function applyUnsafeEditFlag(
	state: WorkspaceState,
	unsafeEditFlag: boolean,
	constraints: UnsafeEditConstraints,
): UnsafeEditFlagResult {
	state.unsafeEdit = false;

	if (!unsafeEditFlag) return "disabled";
	if (constraints.readOnly) return "ignored-read-only";
	if (constraints.isSubagent) return "ignored-subagent";
	if (!constraints.hasUI) return "ignored-non-interactive";

	state.unsafeEdit = true;
	return "enabled";
}
