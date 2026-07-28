/**
 * Continuation guard — shared contract.
 *
 * The guard runs at `agent_end` ("the agent stopped working") and decides
 * whether that stop was premature. Two layers, deliberately separated:
 *
 *   policy.ts — mechanical preconditions only. Asks "may this hook act right
 *               now", never "was the stop correct".
 *   judge.ts  — the rubric. The sole authority on whether a stop was premature.
 */

import { type Static, Type } from "@sinclair/typebox";
import type { AgentMode } from "#core/agent-mode/index.ts";

/** At most this many consecutive nudges before a genuine user message intervenes. */
export const MAX_CONSECUTIVE_NUDGES = 2;

/**
 * Rubric categories. Q/D/H are vetoes (legitimate stop, no nudge);
 * I/R/E are triggers (premature stop, nudge).
 */
export const RUBRIC_CATEGORIES = ["Q", "D", "H", "I", "R", "E"] as const;
export type RubricCategory = (typeof RUBRIC_CATEGORIES)[number];

/** The rubric asks for one short sentence; the bound keeps a runaway reason out of the audit log. */
const REASON_MAX_LENGTH = 400;

/**
 * The verdict shape, declared once. `category` is parameterized because a
 * dispatched run is not offered every category, so the same factory builds both
 * the tool schema the model answers against and the schema the parser validates
 * — they cannot drift.
 *
 * `retrigger` is redundant with the category's polarity on purpose: two
 * independent statements that must agree turn model confusion into no action
 * instead of the wrong action.
 */
export function verdictSchema(categories: readonly RubricCategory[]) {
	return Type.Object(
		{
			retrigger: Type.Boolean(),
			category: Type.Union(categories.map((category) => Type.Literal(category))),
			reason: Type.String({ maxLength: REASON_MAX_LENGTH }),
		},
		{ additionalProperties: false },
	);
}

export const ContinuationVerdictSchema = verdictSchema(RUBRIC_CATEGORIES);
export type ContinuationVerdict = Static<typeof ContinuationVerdictSchema>;

/**
 * Why the guard declined to act. All but `aborted` are decided before the judge
 * runs; `aborted` and a second `pending_user_messages` check are re-read after it,
 * because both go stale across that await.
 */
export type PreconditionBlock =
	| "provider_error"
	| "plan_handoff_active"
	| "pending_user_messages"
	| "cap_reached"
	| "aborted";

export type PolicyOutcome = { act: true } | { act: false; block: PreconditionBlock };

/** Pure inputs to the precondition policy — no Pi API surface. */
export interface PolicyInput {
	/**
	 * The model call itself failed, so there is no agent judgment to nudge. This is
	 * NOT rubric category E, which covers an agent that hit a *tool* error and gave up.
	 */
	providerErrored: boolean;
	planHandoffActive: boolean;
	pendingUserMessages: boolean;
	consecutiveNudges: number;
	maxNudges: number;
}

/** Inputs the rubric judges a stop against. */
export interface JudgeInput {
	goal: string | null;
	/**
	 * Structured task state — parsed `buildStateSnapshot` output, so it nests as JSON
	 * in the prompt rather than as an escaped string, and the judge stays decoupled
	 * from the task schemas.
	 */
	taskSnapshot: unknown;
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
