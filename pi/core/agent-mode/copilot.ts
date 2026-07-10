/**
 * Copilot mode specifics.
 *
 * copilot is the locked, launch-only agent mode: entered solely via `pi --copilot`,
 * immutable once set, and it hides the plan() tool. This module gathers what is
 * peculiar to copilot — the launch-flag reader, the mode predicate, and the name
 * of the built-in tool it disables — so the generic state machine in index.ts
 * stays free of copilot special-casing.
 *
 * Launch seam: `--copilot` is registered by exactly one extension (registerSession).
 * getFlag is per-extension, so other packages cannot read the flag directly without
 * re-registering it (which would trip the loader's flag-conflict diagnostic). Core
 * exposes the launch value through this reader; consumers call isCopilotLaunch().
 */

import type { AgentMode } from "./index.ts";

/** The Pi built-in plan() tool that copilot mode hides. */
export const PLAN_TOOL_NAME = "plan";

/** copilot is the locked, launch-only mode. */
export function isCopilotMode(mode: AgentMode): boolean {
	return mode === "copilot";
}

type CopilotLaunchReader = () => boolean;

// Wiring, not surviving state: core re-registers the reader on every load.
let copilotLaunchReader: CopilotLaunchReader | null = null;

export function setCopilotLaunchReader(reader: CopilotLaunchReader): void {
	copilotLaunchReader = reader;
}

export function isCopilotLaunch(): boolean {
	try {
		return copilotLaunchReader?.() ?? false;
	} catch {
		return false;
	}
}

export function resetCopilotLaunchForTesting(): void {
	copilotLaunchReader = null;
}
