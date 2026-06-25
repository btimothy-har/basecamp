import type { Context, Model } from "@earendil-works/pi-ai";
import { buildGateContext, type GateDecision } from "./gate.ts";
import { type Triage, triageCommand } from "./triage.ts";

export type ReviewAuth = { apiKey?: string; headers?: Record<string, string> };

export interface ReviewDeps {
	resolveModel: () => Promise<{ model: Model<any>; auth: ReviewAuth } | null>;
	recentMessages: () => string[];
	runGate: (args: {
		model: Model<any>;
		auth: ReviewAuth;
		context: Context;
		signal?: AbortSignal;
	}) => Promise<GateDecision | null>;
	confirm: (title: string, body: string) => Promise<boolean>;
	hasUI: boolean;
	signal?: AbortSignal;
	audit: (entry: ReviewAuditEntry) => void;
}

export type ReviewOutcome = { block: true; reason: string } | undefined;

export interface ReviewAuditEntry {
	phase: "triage" | "gate" | "failsafe";
	action: "allow" | "approve" | "block" | "deny";
	category: string;
	command: string;
	reason?: string;
	risk?: GateDecision["risk"];
	note?: string;
}

function truncateCommand(command: string): string {
	return command.length <= 500 ? command : `${command.slice(0, 497)}...`;
}

function blockCategory(command: string): string {
	return /^\s*bq\b/.test(command) ? "bq-query" : "triage-block";
}

function confirmationBody(command: string, decision: GateDecision): string {
	return `Command:\n${command}\n\nRisk: ${decision.risk}\nReason: ${decision.reason}`;
}

export async function reviewBashCommand(command: string, deps: ReviewDeps): Promise<ReviewOutcome> {
	const t = triageCommand(command);
	const auditCommand = truncateCommand(command);
	const audit = (entry: Omit<ReviewAuditEntry, "command">) => {
		try {
			deps.audit({ ...entry, command: auditCommand });
		} catch {
			// Auditing must never make the bash reviewer fail open or fail closed differently.
		}
	};
	const failSafe = async (triage: Extract<Triage, { kind: "gate" }>, why: string): Promise<ReviewOutcome> => {
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

			audit({
				phase: "failsafe",
				action: ok ? "approve" : "deny",
				category: triage.category,
				reason: why,
				note: "escalated",
			});

			return ok
				? undefined
				: { block: true, reason: `Command blocked: reviewer unavailable (${why}) and user declined.` };
		}

		audit({
			phase: "failsafe",
			action: "deny",
			category: triage.category,
			reason: why,
			note: "no-ui",
		});
		return {
			block: true,
			reason: `Reviewer unavailable (${why}); blocked because there is no interactive UI to confirm. Run it yourself if intended.`,
		};
	};

	if (t.kind === "allow") return undefined;

	if (t.kind === "block") {
		audit({ phase: "triage", action: "block", category: blockCategory(command), reason: t.reason });
		return { block: true, reason: t.reason };
	}

	try {
		const resolved = await deps.resolveModel();
		if (resolved === null) return await failSafe(t, "reviewer model unavailable");

		const context = buildGateContext(deps.recentMessages(), command);
		const decision = await deps.runGate({
			model: resolved.model,
			auth: resolved.auth,
			context,
			signal: deps.signal,
		});
		if (decision === null) return await failSafe(t, "reviewer returned no decision");

		let effective = decision.decision;
		if (t.failClosed && effective === "approve") effective = "route_to_user";

		switch (effective) {
			case "approve":
				audit({
					phase: "gate",
					action: "approve",
					category: t.category,
					reason: decision.reason,
					risk: decision.risk,
				});
				return undefined;
			case "deny":
				audit({
					phase: "gate",
					action: "deny",
					category: t.category,
					reason: decision.reason,
					risk: decision.risk,
				});
				return { block: true, reason: decision.reason };
			case "route_to_user": {
				if (!deps.hasUI) {
					audit({
						phase: "gate",
						action: "deny",
						category: t.category,
						reason: decision.reason,
						risk: decision.risk,
						note: "no-ui",
					});
					return {
						block: true,
						reason: `Requires user review (${decision.reason}); not available without an interactive UI.`,
					};
				}

				const ok = await deps.confirm("Approve command?", confirmationBody(command, decision));
				audit({
					phase: "gate",
					action: ok ? "approve" : "deny",
					category: t.category,
					reason: decision.reason,
					risk: decision.risk,
					note: "route_to_user",
				});
				return ok ? undefined : { block: true, reason: "User declined the command." };
			}
		}
	} catch (error) {
		const reason = error instanceof Error ? error.message : "unexpected reviewer error";
		return await failSafe(t, reason);
	}
}
