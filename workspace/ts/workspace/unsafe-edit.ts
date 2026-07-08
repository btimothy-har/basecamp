import type { UnsafeEditConstraints, UnsafeEditFlagResult, WorkspaceState } from "#core/platform/workspace.ts";

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
