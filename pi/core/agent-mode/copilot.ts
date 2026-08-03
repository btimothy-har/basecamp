/**
 * Copilot mode specifics.
 *
 * copilot is the locked, launch-only agent mode: entered solely via `pi --copilot`,
 * immutable once set, and it blocks plan() at call time (the tool stays registered
 * — and therefore visible in the API tools array — because it must remain callable
 * in every other mode). This module gathers what is peculiar to copilot — the
 * launch predicate, the mode predicate, and the name of the tool it blocks — so
 * the generic state machine in index.ts stays free of copilot special-casing.
 *
 * The launch predicate reads argv rather than `pi.getFlag("copilot")` because Pi
 * applies CLI flag values only after every extension factory has run. Consumers
 * that gate *registration* on copilot (`pi/workstreams/index.ts`) have no flag
 * value to read that early, and argv is the only copilot signal that exists then.
 * registerSession declares the flag off COPILOT_FLAG_NAME — without the
 * declaration Pi rejects `--copilot` as an unknown option — so one name spans
 * both the declaration and this read.
 *
 * Deliberately not a BASECAMP_* env var: subagents inherit the parent environment,
 * so a copilot var would make every dispatched agent a copilot. Copilot is a
 * property of this process's launch and must not propagate.
 */

import type { AgentMode } from "./index.ts";

/** The plan() tool that copilot mode blocks at call time (pi/tasks/tools/guards.ts). */
export const PLAN_TOOL_NAME = "plan";

/** Registered by registerSession, read here — one name so the two cannot drift. */
export const COPILOT_FLAG_NAME = "copilot";

const COPILOT_FLAG = `--${COPILOT_FLAG_NAME}`;

/** copilot is the locked, launch-only mode. */
export function isCopilotMode(mode: AgentMode): boolean {
	return mode === "copilot";
}

/**
 * True when this process was launched with `--copilot`. Pi coerces a boolean flag
 * to true whatever value it parses, so `--copilot=false` is a copilot launch too.
 *
 * Coarser than Pi's parser in one case: Pi reads a built-in value-taking flag's
 * value unconditionally, so `pi --model --copilot` binds the token as the model
 * and is not a copilot launch, while this returns true. Recognising that would
 * mean copying Pi's list of value-taking flags, and a stale copy of that list
 * fails more quietly than this does — the invocation is already malformed.
 */
export function isCopilotLaunch(): boolean {
	return process.argv.slice(2).some((arg) => arg === COPILOT_FLAG || arg.startsWith(`${COPILOT_FLAG}=`));
}
