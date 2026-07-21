import type { UnsafeEditConstraints, UnsafeEditFlagResult, WorkspaceState } from "./state.ts";

export function applyUnsafeEditFlag(
	state: WorkspaceState,
	unsafeEditFlag: boolean,
	constraints: UnsafeEditConstraints,
): UnsafeEditFlagResult {
	state.unsafeEdit = false;

	if (!unsafeEditFlag) return "disabled";
	if (constraints.readOnly) return "ignored-read-only";
	if (!constraints.sandboxed && constraints.isSubagent) return "ignored-subagent";
	if (!constraints.sandboxed && !constraints.hasUI) return "ignored-non-interactive";

	state.unsafeEdit = true;
	return "enabled";
}
