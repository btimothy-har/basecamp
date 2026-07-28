/**
 * Continuation guard — the rubric the fast model judges a stop against.
 *
 * Composed from named parts rather than carved out of a finished string. The
 * subagent variant must drop veto Q, and stripping that bullet from an
 * assembled prompt by line prefix would silently re-enable it the moment the
 * wording is reflowed — a formatting change would then quietly restore the
 * exact behavior the divergence exists to prevent.
 *
 * `offeredCategories` lives here for the same reason: the categories the tool
 * schema offers and the vetoes the prompt states are one decision, so they
 * cannot drift apart.
 */

import { RUBRIC_CATEGORIES, type RubricCategory } from "./types.ts";

const INTRO = `You are judging whether a coding agent's stop was premature. The agent has stopped producing tool calls and returned control. Decide whether it should be nudged to continue. Call the continuation_verdict tool exactly once. Keep the reason to one short sentence.`;

const VETO_HEADING = `Do NOT retrigger (retrigger: false) if any of these hold:`;
const VETO_Q = `- Q (Asked): the final message asks the user anything — a question, a choice, a confirmation, or permission. ANY question counts, including one whose answer looks obvious.`;
const VETO_D = `- D (Delivered): the requested work appears done — the goal is satisfied, or in analysis/planning mode findings, a synthesis, or a plan has been presented for review.`;
const VETO_H = `- H (Held): it is waiting on a human action or an external event it cannot progress itself.`;

const TRIGGER_HEADING = `Otherwise retrigger (retrigger: true), specifically when:`;
const TRIGGER_I = `- I (Intent): the final message states or implies a next action that was not performed.`;
const TRIGGER_R = `- R (Remaining): the goal or task state shows work left, and the message neither asks nor claims completion.`;
const TRIGGER_E = `- E (Error): it stopped at an unresolved error without either recovering or delivering a conclusion.`;

const TIE_BREAK = `Tie-break: when uncertain, do NOT retrigger. A wrong stop costs the user one keystroke; a wrong continue burns a whole agent run.`;

const SUBAGENT_CLAUSE = `Subagent divergence: this agent was dispatched by another agent and has no user, so a question is unanswerable and stopping on one wastes the run. Veto Q does not apply here: a question in the final message is NOT a reason to stop. If the agent faces a question or choice, it should decide and proceed, or report the blocker as its deliverable. Vetoes D and H still apply.`;

const INPUT_FORMAT = `Input arrives as JSON with goal, task_snapshot, mode, read_only, final_assistant_message, and recent_user_messages (most-recent-last) fields.`;

/** Categories the tool schema may offer; Q is withheld wherever it is not a valid stop reason. */
export function offeredCategories(subagent: boolean): readonly RubricCategory[] {
	return subagent ? RUBRIC_CATEGORIES.filter((category) => category !== "Q") : RUBRIC_CATEGORIES;
}

const VETO_CATEGORIES = new Set<RubricCategory>(["Q", "D", "H"]);

/** Polarity belongs to the category, stated here beside the vetoes and triggers it describes. */
export function categoryRetriggers(category: RubricCategory): boolean {
	return !VETO_CATEGORIES.has(category);
}

export function buildRubric(subagent: boolean): string {
	const vetoes = subagent ? [VETO_D, VETO_H] : [VETO_Q, VETO_D, VETO_H];
	const sections = [
		INTRO,
		[VETO_HEADING, ...vetoes].join("\n"),
		[TRIGGER_HEADING, TRIGGER_I, TRIGGER_R, TRIGGER_E].join("\n"),
		TIE_BREAK,
		...(subagent ? [SUBAGENT_CLAUSE] : []),
		INPUT_FORMAT,
	];
	return sections.join("\n\n");
}

/** The primary-session rubric — a complete, usable prompt, not a template. */
export const CONTINUATION_RUBRIC = buildRubric(false);
