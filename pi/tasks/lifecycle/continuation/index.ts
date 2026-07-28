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
import { recentUserMessages } from "#core/session/user-context.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import { buildStateSnapshot } from "#tasks/lifecycle/text.ts";
import { buildJudgeContext, resolveJudgeModel, runJudge } from "./judge.ts";
import { finalAssistantText, providerErrored } from "./messages.ts";
import { createNudgeBudget, evaluatePreconditions } from "./policy.ts";
import { type ContinuationAuditEntry, type ContinuationVerdict, MAX_CONSECUTIVE_NUDGES } from "./types.ts";

export const CONTINUATION_NUDGE_TYPE = "basecamp-continuation-nudge";
/** Bounds the judge call, which holds run settlement open while it is in flight. */
const JUDGE_TIMEOUT_MS = 20_000;
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
		subagent: boolean;
		signal: AbortSignal;
	}) => Promise<ContinuationVerdict | null>;
}

/**
 * The nudge is static: the judge's `reason` stays in the audit trail and never
 * reaches an agent. Model-authored text routed through a system-trusted frame
 * would launder whatever the judge read — file contents, tool output, a peer's
 * message — into apparent harness instruction, and a reason that contradicted
 * the verdict would assert something false about the stop. Both variants offer
 * three exits so a wrongly nudged agent can settle in one call.
 */
const PRIMARY_NUDGE =
	"This stop looked premature. If work remains, continue it now.\n" +
	"If you genuinely need a decision from the user, call escalate. If the work is complete, close it out with a work summary.";

// A dispatched run's recorded result is whatever its final message says, so a
// continuation that omits the deliverable discards it.
const SUBAGENT_NUDGE =
	"This stop looked premature. If work remains, continue it now.\n" +
	"No user is available to answer questions, so decide on your own judgment; if you are genuinely blocked, report the blocker as your deliverable.\n" +
	"Restate your substantive result in full in your final response — anything you do not restate is lost.";

function nudgeContent(subagent: boolean): string {
	return `<system-reminder>\n${subagent ? SUBAGENT_NUDGE : PRIMARY_NUDGE}\n</system-reminder>`;
}

export function registerContinuationGuard(pi: ExtensionAPI, runtime: TasksRuntime, deps: ContinuationGuardDeps): void {
	const isSubagentRun = deps.isSubagentRun ?? (() => isSubagent());
	const isReadOnly = deps.isReadOnly ?? (() => pi.getFlag("read-only") === true);
	const resolveModel = deps.resolveModel ?? ((ctx: ExtensionContext) => resolveJudgeModel(ctx));
	const judge = deps.judge ?? ((args) => runJudge(args));

	const budget = createNudgeBudget();

	const audit = (entry: ContinuationAuditEntry): void => {
		try {
			pi.appendEntry(AUDIT_ENTRY_TYPE, entry);
		} catch {
			// An unrecorded decision must never change the decision.
		}
	};

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

			const messages = event.messages;
			const outcome = evaluatePreconditions({
				providerErrored: providerErrored(messages),
				planHandoffActive: deps.planHandoffActive(),
				pendingUserMessages: ctx.hasPendingMessages(),
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

			const context = buildJudgeContext({
				goal: runtime.state.goal,
				// buildStateSnapshot returns JSON.stringify output, so this cannot throw.
				taskSnapshot: JSON.parse(buildStateSnapshot(runtime.state)),
				mode: getAgentMode(),
				readOnly: isReadOnly(),
				subagent,
				finalAssistantMessage: stopMessage,
				recentUserMessages: recentUserMessages(ctx.sessionManager.getEntries()),
			});

			// The run is still streaming here, so the session cannot settle until this
			// resolves. An unbounded call would wedge every stop with no way out, and
			// ctx.signal alone is not enough because it only fires on an explicit abort.
			const deadline = AbortSignal.timeout(JUDGE_TIMEOUT_MS);
			const signal = ctx.signal ? AbortSignal.any([ctx.signal, deadline]) : deadline;

			let verdict: ContinuationVerdict | null;
			try {
				verdict = await judge({ model: resolved.model, auth: resolved.auth, context, subagent, signal });
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

			// Both checks are re-read because the pre-await samples are stale, and the judge
			// window is exactly when a user aborts or types: the queues are drained immediately
			// before agent_end, so almost nothing arrives before the await.
			if (ctx.signal?.aborted) {
				// Pi resumes on any queued message without checking for an abort, so nudging
				// here would restart the run the user just cancelled.
				record({ outcome: "blocked", block: "aborted" });
				return;
			}
			if (ctx.hasPendingMessages()) {
				record({ outcome: "blocked", block: "pending_user_messages" });
				return;
			}

			budget.recordNudge();
			pi.sendMessage(
				{ customType: CONTINUATION_NUDGE_TYPE, content: nudgeContent(subagent), display: false },
				{ deliverAs: "followUp" },
			);
			audit({
				outcome: "nudged",
				subagent,
				consecutiveNudges: budget.consecutive,
				category: verdict.category,
				reason: verdict.reason,
			});
			// Best-effort UI comes last: a throwing notify must not lose the record of a nudge
			// that has already been delivered.
			if (ctx.hasUI) ctx.ui.notify(`↻ continuing — ${verdict.reason}`, "info");
		} catch {
			// The guard is advisory: a failure here must never disturb the run that just ended.
		}
	});
}
