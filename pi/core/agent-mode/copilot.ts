/**
 * Copilot mode specifics.
 *
 * copilot is the locked, launch-only agent mode: entered solely via `pi --copilot`,
 * immutable once set, and it hides the plan() tool. This module gathers what is
 * peculiar to copilot — the launch predicate, the mode predicate, and the name of
 * the built-in tool it disables — so the generic state machine in index.ts stays
 * free of copilot special-casing.
 *
 * The launch predicate reads argv rather than `pi.getFlag("copilot")` because Pi
 * applies CLI flag values only after every extension factory has run. Consumers
 * that gate *registration* on copilot (`pi/workstreams/index.ts`) have no flag
 * value to read that early, and argv is the only copilot signal that exists then.
 * registerSession still declares the flag — without it Pi rejects `--copilot` as
 * an unknown option — so the flag is declared there and read here.
 *
 * Deliberately not a BASECAMP_* env var: subagents inherit the parent environment,
 * so a copilot var would make every dispatched agent a copilot. Copilot is a
 * property of this process's launch and must not propagate.
 */

import type { AgentMode } from "./index.ts";

/** The Pi built-in plan() tool that copilot mode hides. */
export const PLAN_TOOL_NAME = "plan";

const COPILOT_FLAG = "--copilot";

/** copilot is the locked, launch-only mode. */
export function isCopilotMode(mode: AgentMode): boolean {
	return mode === "copilot";
}

/**
 * True when this process was launched with `--copilot`. Pi coerces a boolean flag
 * to true whatever value it parses, so `--copilot=false` is a copilot launch too.
 */
export function isCopilotLaunch(): boolean {
	return process.argv.some((arg) => arg === COPILOT_FLAG || arg.startsWith(`${COPILOT_FLAG}=`));
}
