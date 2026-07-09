import assert from "node:assert/strict";
import type { Model } from "@earendil-works/pi-ai";
import type { GateDecision } from "../reviewer/gate.ts";
import { type ReviewAuditEntry, type ReviewDeps, reviewBashCommand } from "../reviewer/review.ts";

export const fakeModel: Model<any> = {
	id: "claude-haiku",
	name: "Claude Haiku",
	api: "anthropic-messages",
	provider: "anthropic",
	baseUrl: "https://example.test",
	reasoning: false,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
	contextWindow: 200_000,
	maxTokens: 4096,
};

type FakeNotification = { message: string; type?: "info" | "warning" | "error" };

export interface FakeReviewHarness {
	deps: ReviewDeps;
	auditEntries: ReviewAuditEntry[];
	confirmBodies: string[];
	notifications: FakeNotification[];
	confirmCalls: () => number;
	resolveModelCalls: () => number;
	runGateCalls: () => number;
}

export function makeDecision(decision: GateDecision["decision"], reason = "Looks safe."): GateDecision {
	return { decision, risk: decision === "approve" ? "local" : "destructive", reason };
}

export function makeDeps(
	overrides: Partial<{
		resolveModel: ReviewDeps["resolveModel"];
		runGate: ReviewDeps["runGate"];
		confirm: ReviewDeps["confirm"];
		hasUI: boolean;
		isSubagent: boolean;
	}> = {},
): FakeReviewHarness {
	const auditEntries: ReviewAuditEntry[] = [];
	const confirmBodies: string[] = [];
	const notifications: FakeNotification[] = [];
	let resolveModelCalls = 0;
	let runGateCalls = 0;
	let confirmCalls = 0;

	const deps: ReviewDeps = {
		resolveModel: async () => {
			resolveModelCalls += 1;
			if (overrides.resolveModel) return overrides.resolveModel();
			return { model: fakeModel, auth: { apiKey: "test-key" } };
		},
		recentMessages: () => ["Please make the requested repository change."],
		runGate: async (args) => {
			runGateCalls += 1;
			if (overrides.runGate) return overrides.runGate(args);
			return makeDecision("approve");
		},
		confirm: async (title, body) => {
			confirmCalls += 1;
			assert.ok(title === "Approve command?" || title === "Reviewer unavailable — approve command?");
			confirmBodies.push(body);
			if (overrides.confirm) return overrides.confirm(title, body);
			return true;
		},
		hasUI: overrides.hasUI ?? true,
		isSubagent: overrides.isSubagent ?? false,
		audit: (entry) => auditEntries.push(entry),
		notify: (message, type) => notifications.push({ message, type }),
	};

	return {
		deps,
		auditEntries,
		confirmBodies,
		notifications,
		confirmCalls: () => confirmCalls,
		resolveModelCalls: () => resolveModelCalls,
		runGateCalls: () => runGateCalls,
	};
}

export async function assertAuditedNonAllow(
	command: string,
	deps: ReviewDeps,
	auditEntries: ReviewAuditEntry[],
): Promise<void> {
	await reviewBashCommand(command, deps);
	assert.ok(auditEntries.length > 0, `${command} should emit at least one audit entry`);
}
