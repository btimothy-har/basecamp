import type { Context, Model } from "@earendil-works/pi-ai";
import { isTriviallySafe } from "./fast-path.ts";
import { buildGateContext, type GateDecision } from "./llm.ts";

export type ReviewAuth = { apiKey?: string; headers?: Record<string, string | null> };

const SUBAGENT_APPROVE_CATEGORIES = new Set<GateDecision["category"]>(["git-mutation"]);

export interface ReviewDeps {
	resolveModel: () => Promise<{ model: Model<any>; auth: ReviewAuth } | null>;
	recentMessages: () => string[];
	/** The directory bash commands run from (the workspace effective cwd). */
	cwd: string;
	runGate: (args: {
		model: Model<any>;
		auth: ReviewAuth;
		context: Context;
		signal?: AbortSignal;
	}) => Promise<GateDecision | null>;
	confirm: (title: string, body: string) => Promise<boolean>;
	hasUI: boolean;
	isSubagent: boolean;
	/** When true the LLM gate is skipped — the fast path still runs first. */
	paused: boolean;
	signal?: AbortSignal;
	audit: (entry: ReviewAuditEntry) => void;
	notify: (message: string, type?: "info" | "warning" | "error") => void;
}

export type ReviewOutcome = { block: true; reason: string } | undefined;

export interface ReviewAuditEntry {
	phase: "gate" | "failsafe";
	action: "approve" | "deny";
	command: string;
	category?: GateDecision["category"];
	reason?: string;
	risk?: GateDecision["risk"];
	note?: string;
}

function truncateCommand(command: string): string {
	return command.length <= 500 ? command : `${command.slice(0, 497)}...`;
}

function confirmationBody(command: string, decision: GateDecision): string {
	return `Command:\n${command}\n\nRisk: ${decision.risk}\nReason: ${decision.reason}`;
}

/**
 * Every path out of here either matched the fast path, carries a gate verdict, or went through the
 * failsafe. Nothing else may return undefined: a static check that grants permission is exactly the
 * shape of bug this reviewer was rebuilt to make impossible.
 */
export async function reviewBashCommand(command: string, deps: ReviewDeps): Promise<ReviewOutcome> {
	if (isTriviallySafe(command)) return undefined;

	// The escape hatch: skip the LLM gate entirely. The fast path above already
	// ran, so only non-trivial commands reach here. This is a temporary
	// session-level toggle (`/bash-guard off`), not a security control.
	if (deps.paused) return undefined;

	const auditCommand = truncateCommand(command);
	const audit = (entry: Omit<ReviewAuditEntry, "command">) => {
		try {
			deps.audit({ ...entry, command: auditCommand });
		} catch {
			// Auditing must never make the bash reviewer fail open or fail closed differently.
		}
	};
	const notify = (message: string, type?: "info" | "warning" | "error") => {
		try {
			deps.notify(message, type);
		} catch {
			// Notifications are best-effort UI feedback and must not change the gate outcome.
		}
	};
	const failSafe = async (why: string): Promise<ReviewOutcome> => {
		if (deps.hasUI) {
			let ok = false;
			try {
				ok = await deps.confirm(
					"Reviewer unavailable — approve command?",
					`The bash reviewer could not evaluate this command.\n\nReason: ${why}\n\nCommand:\n${command}\n\nApprove and run it anyway?`,
				);
			} catch {
				ok = false;
			}

			audit({ phase: "failsafe", action: ok ? "approve" : "deny", reason: why, note: "escalated" });

			return ok
				? undefined
				: { block: true, reason: `Command blocked: reviewer unavailable (${why}) and user declined.` };
		}

		audit({ phase: "failsafe", action: "deny", reason: why, note: "no-ui" });
		return {
			block: true,
			reason: `Reviewer unavailable (${why}); blocked because there is no interactive UI to confirm. Run it yourself if intended.`,
		};
	};

	try {
		const resolved = await deps.resolveModel();
		if (resolved === null) return await failSafe("reviewer model unavailable");

		const context = buildGateContext(deps.recentMessages(), command, deps.cwd);
		const decision = await deps.runGate({
			model: resolved.model,
			auth: resolved.auth,
			context,
			signal: deps.signal,
		});
		if (decision === null) return await failSafe("reviewer returned no decision");

		const category = decision.category;
		let effective = decision.decision;
		// Defence in depth: a single model slip toward approve must not carry an irreversible command.
		if (effective === "approve" && decision.risk === "destructive") effective = "route_to_user";

		switch (effective) {
			case "approve":
				audit({ phase: "gate", action: "approve", category, reason: decision.reason, risk: decision.risk });
				notify(`🛡 reviewer approved · ${decision.risk}: ${decision.reason}`, "info");
				return undefined;
			case "deny":
				audit({ phase: "gate", action: "deny", category, reason: decision.reason, risk: decision.risk });
				notify(`🛡 reviewer blocked: ${decision.reason}`, "warning");
				return { block: true, reason: decision.reason };
			case "route_to_user": {
				if (deps.hasUI) {
					const ok = await deps.confirm("Approve command?", confirmationBody(command, decision));
					audit({
						phase: "gate",
						action: ok ? "approve" : "deny",
						category,
						reason: decision.reason,
						risk: decision.risk,
						note: "route_to_user",
					});
					return ok ? undefined : { block: true, reason: "User declined the command." };
				}

				if (deps.isSubagent) {
					const permit = SUBAGENT_APPROVE_CATEGORIES.has(category);
					audit({
						phase: "gate",
						action: permit ? "approve" : "deny",
						category,
						reason: decision.reason,
						risk: decision.risk,
						note: "subagent-collapse",
					});
					return permit
						? undefined
						: {
								block: true,
								reason: `Requires human review (${decision.reason}); auto-denied for an autonomous agent. Report this command back to the parent session instead of retrying.`,
							};
				}

				audit({
					phase: "gate",
					action: "deny",
					category,
					reason: decision.reason,
					risk: decision.risk,
					note: "no-ui",
				});
				return {
					block: true,
					reason: `Requires user review (${decision.reason}); not available without an interactive UI.`,
				};
			}
		}
	} catch (error) {
		const reason = error instanceof Error ? error.message : "unexpected reviewer error";
		return await failSafe(reason);
	}
}
