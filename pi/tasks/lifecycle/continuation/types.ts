/**
 * Continuation guard — shared contract.
 *
 * The guard runs at `agent_end` ("the agent stopped working") and decides
 * whether that stop was premature. Two layers, deliberately separated:
 *
 *   policy.ts — mechanical preconditions + the stop_work contract. Asks only
 *               "may this hook act right now", never "was the stop correct".
 *   judge.ts  — the rubric. The sole authority on whether a stop was premature.
 */

import type { AgentMode } from "#core/agent-mode/index.ts";

/** At most this many consecutive nudges before a genuine user message intervenes. */
export const MAX_CONSECUTIVE_NUDGES = 2;

/**
 * Rubric categories. Q/D/H are vetoes (legitimate stop, no nudge);
 * I/R/E are triggers (premature stop, nudge).
 */
export const RUBRIC_CATEGORIES = ["Q", "D", "H", "I", "R", "E"] as const;
export type RubricCategory = (typeof RUBRIC_CATEGORIES)[number];

export interface ContinuationVerdict {
	retrigger: boolean;
	category: RubricCategory;
	reason: string;
}

/** Why the guard declined to act without consulting the rubric. */
export type PreconditionBlock =
	| "will_retry"
	| "plan_handoff_active"
	| "pending_user_messages"
	| "cap_reached"
	| "stop_work";

export type PolicyOutcome = { act: true } | { act: false; block: PreconditionBlock };

/** Pure inputs to the precondition policy — no Pi API surface. */
export interface PolicyInput {
	willRetry: boolean;
	planHandoffActive: boolean;
	pendingUserMessages: boolean;
	stopWorkThisRun: boolean;
	consecutiveNudges: number;
	maxNudges: number;
}

/** Inputs the rubric judges a stop against. */
export interface JudgeInput {
	goal: string | null;
	/** Pre-rendered `buildStateSnapshot` output, so the judge stays decoupled from task schemas. */
	taskSnapshot: string;
	mode: AgentMode;
	readOnly: boolean;
	subagent: boolean;
	finalAssistantMessage: string;
	recentUserMessages: string[];
}

export type ContinuationOutcome = "blocked" | "no_verdict" | "held" | "nudged";

/** Audit record appended for every stop the guard evaluates. */
export interface ContinuationAuditEntry {
	outcome: ContinuationOutcome;
	subagent: boolean;
	consecutiveNudges: number;
	block?: PreconditionBlock;
	category?: RubricCategory;
	reason?: string;
}
