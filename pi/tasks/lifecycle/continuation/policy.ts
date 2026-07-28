/**
 * Continuation guard — precondition policy.
 *
 * Decides only whether the guard's `agent_end` hook may act at all; the
 * rubric judge owns "was the stop premature". Every condition here is
 * mechanical — none of them asks whether continuing would be correct.
 *
 * `providerErrored` stands in for Pi's own `willRetry`, which extensions never
 * receive: Pi attaches it to the internal session event, not the extension
 * event, and derives it from the last assistant message being a retryable
 * error. We read that same message, so the signal is equivalent or wider — it
 * also covers non-retryable errors and exhausted retries, none of which are a
 * premature stop. It must not be conflated with rubric category E, which is
 * about an agent abandoning work after a *tool* failure.
 *
 * This module deliberately has
 * no notion of escalation: an earlier design suppressed acting whenever
 * `escalate` had been called during the run, which is wrong because a stop
 * occurring later in the same run — long after that escalation was resolved —
 * would then be denied a legitimate nudge. Escalation history is not a
 * precondition; only the five conditions below are.
 */

import type { PolicyInput, PolicyOutcome, PreconditionBlock } from "./types.ts";

function block(reason: PreconditionBlock): PolicyOutcome {
	return { act: false, block: reason };
}

/**
 * Check order is contract: the reported block is audited, so the first
 * condition that holds wins and determines the recorded reason.
 */
export function evaluatePreconditions(input: PolicyInput): PolicyOutcome {
	if (input.providerErrored) return block("provider_error");
	if (input.planHandoffActive) return block("plan_handoff_active");
	if (input.pendingUserMessages) return block("pending_user_messages");
	if (input.consecutiveNudges >= input.maxNudges) return block("cap_reached");
	return { act: true };
}

/**
 * The caller, not the budget, decides when a reset applies: the guard nudges
 * via a hidden CUSTOM message while genuine user input arrives as a USER
 * message, so only the caller can tell the two apart. Wiring `reset()` to
 * user messages is what makes the cap mean "per user prompt" instead of "per
 * run", and what keeps the guard's own nudge from zeroing its own counter.
 */
export interface NudgeBudget {
	readonly consecutive: number;
	recordNudge(): void;
	reset(): void;
}

export function createNudgeBudget(): NudgeBudget {
	let consecutive = 0;
	return {
		get consecutive() {
			return consecutive;
		},
		recordNudge() {
			consecutive += 1;
		},
		reset() {
			consecutive = 0;
		},
	};
}
