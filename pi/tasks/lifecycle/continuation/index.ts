/**
 * Continuation guard — nudges an agent that stopped working prematurely.
 *
 * Fires at `agent_end`, which is the moment an agent stops: the run ended
 * because the model stopped calling tools. `turn_end` is per LLM response
 * inside a run, and `agent_settled` fires after Pi's continuation loop has
 * already exited — in a dispatched agent's print-mode process, too late to act.
 *
 * A queued `followUp` here is what restarts the work: Pi checks queued messages
 * after awaited `agent_end` handlers and continues the run.
 *
 * `planHandoffActive` arrives as a callback rather than a `PlanAccess` import so
 * this layer does not depend on `tools/`, which sits above it.
 */

import type { Api, Context, Model } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isCopilotMode } from "#core/agent-mode/copilot.ts";
import { getAgentMode } from "#core/agent-mode/index.ts";
import { errorMessage } from "#core/errors.ts";
import { isSubagent } from "#core/host/env.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import { buildStateSnapshot, isCompleteTaskStopWorkDetails } from "#tasks/lifecycle/text.ts";
import { buildJudgeContext, resolveJudgeModel, runJudge } from "./judge.ts";
import { finalAssistantText, providerErrored, recentUserMessages } from "./messages.ts";
import { createNudgeBudget, evaluatePreconditions } from "./policy.ts";
import { type ContinuationAuditEntry, type ContinuationVerdict, MAX_CONSECUTIVE_NUDGES } from "./types.ts";

export const CONTINUATION_NUDGE_TYPE = "basecamp-continuation-nudge";
const AUDIT_ENTRY_TYPE = "continuation-guard";

type ResolvedJudgeModel = { model: Model<Api>; auth: { apiKey?: string; headers?: Record<string, string> } };

export interface ContinuationGuardDeps {
	planHandoffActive: () => boolean;
	isSubagentRun?: () => boolean;
	isReadOnly?: () => boolean;
	resolveModel?: (ctx: ExtensionContext) => Promise<ResolvedJudgeModel | null>;
	judge?: (args: {
		model: Model<Api>;
		auth: ResolvedJudgeModel["auth"];
		context: Context;
	}) => Promise<ContinuationVerdict | null>;
}

function nudgeContent(subagent: boolean, reason: string): string {
	const body = subagent
		? `Continuation check — work appears to remain: ${reason}\n` +
			"You are a dispatched agent, so no user will answer a question: decide on your own judgment and proceed. " +
			"If you are genuinely blocked, state the blocker as your deliverable in your final response."
		: `Continuation check — you stopped without asking anything and without signalling completion: ${reason}\n` +
			"Continue the work where you left off. If you genuinely need a decision from the user, call escalate. " +
			"If the work really is finished, close it out with complete_task.";
	return `<system-reminder>\n${body}\n</system-reminder>`;
}

export function registerContinuationGuard(pi: ExtensionAPI, runtime: TasksRuntime, deps: ContinuationGuardDeps): void {
	const isSubagentRun = deps.isSubagentRun ?? (() => isSubagent());
	const isReadOnly = deps.isReadOnly ?? (() => pi.getFlag("read-only") === true);
	const resolveModel = deps.resolveModel ?? ((ctx: ExtensionContext) => resolveJudgeModel(ctx));
	const judge = deps.judge ?? ((args) => runJudge(args));

	const budget = createNudgeBudget();
	let stopWorkThisRun = false;

	const audit = (entry: ContinuationAuditEntry): void => {
		try {
			pi.appendEntry(AUDIT_ENTRY_TYPE, entry);
		} catch {
			// An unrecorded decision must never change the decision.
		}
	};

	pi.on("tool_result", (event) => {
		if (event.toolName !== "complete_task" || event.isError) return;
		if (isCompleteTaskStopWorkDetails(event.details)) stopWorkThisRun = true;
	});

	// Only a genuine user message resets the budget. The nudge is a custom message,
	// so it cannot clear its own counter; plan handoffs and peer messages arrive as
	// user messages and legitimately do.
	pi.on("message_start", (event) => {
		if (event.message.role === "user") budget.reset();
	});

	pi.on("agent_end", async (event, ctx) => {
		const subagent = isSubagentRun();
		const record = (entry: Omit<ContinuationAuditEntry, "subagent" | "consecutiveNudges">): void =>
			audit({ ...entry, subagent, consecutiveNudges: budget.consecutive });

		try {
			if (isCopilotMode(getAgentMode())) return;

			const messages = event.messages ?? [];
			const outcome = evaluatePreconditions({
				providerErrored: providerErrored(messages),
				planHandoffActive: deps.planHandoffActive(),
				pendingUserMessages: ctx.hasPendingMessages(),
				stopWorkThisRun,
				consecutiveNudges: budget.consecutive,
				maxNudges: MAX_CONSECUTIVE_NUDGES,
			});
			if (!outcome.act) {
				record({ outcome: "blocked", block: outcome.block });
				return;
			}

			const stopMessage = finalAssistantText(messages);
			if (stopMessage === "") {
				record({ outcome: "no_verdict", reason: "no assistant message to judge" });
				return;
			}

			const resolved = await resolveModel(ctx);
			if (!resolved) {
				record({ outcome: "no_verdict", reason: "fast model unavailable" });
				return;
			}

			// Deliberately unsignalled: `ctx.signal` may already be aborted as the turn
			// winds down, which would abort every judge call and silently disable the guard.
			const context = buildJudgeContext({
				goal: runtime.state.goal,
				// buildStateSnapshot returns JSON.stringify output, so this cannot throw.
				taskSnapshot: JSON.parse(buildStateSnapshot(runtime.state)),
				mode: getAgentMode(),
				readOnly: isReadOnly(),
				subagent,
				finalAssistantMessage: stopMessage,
				recentUserMessages: recentUserMessages(ctx.sessionManager),
			});

			let verdict: ContinuationVerdict | null;
			try {
				verdict = await judge({ model: resolved.model, auth: resolved.auth, context });
			} catch (error) {
				record({ outcome: "no_verdict", reason: errorMessage(error) });
				return;
			}
			if (!verdict) {
				record({ outcome: "no_verdict", reason: "judge returned no decision" });
				return;
			}
			if (!verdict.retrigger) {
				record({ outcome: "held", category: verdict.category, reason: verdict.reason });
				return;
			}

			budget.recordNudge();
			pi.sendMessage(
				{ customType: CONTINUATION_NUDGE_TYPE, content: nudgeContent(subagent, verdict.reason), display: false },
				{ deliverAs: "followUp" },
			);
			if (ctx.hasUI) ctx.ui.notify(`↻ continuing — ${verdict.reason}`, "info");
			audit({
				outcome: "nudged",
				subagent,
				consecutiveNudges: budget.consecutive,
				category: verdict.category,
				reason: verdict.reason,
			});
		} catch {
			// The guard is advisory: a failure here must never disturb the run that just ended.
		} finally {
			stopWorkThisRun = false;
		}
	});
}
