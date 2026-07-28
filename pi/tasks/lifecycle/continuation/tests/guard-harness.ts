/** Shared fake Pi harness for the continuation-guard tests. */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type ContinuationGuardDeps, registerContinuationGuard } from "#tasks/lifecycle/continuation/index.ts";
import type { ContinuationAuditEntry, ContinuationVerdict } from "#tasks/lifecycle/continuation/types.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";

type Handler = (event: any, ctx: ExtensionContext) => unknown;

interface SentMessage {
	customType: string;
	content: string;
	display: boolean;
	deliverAs: string;
}

export class FakePi {
	readonly sent: SentMessage[] = [];
	readonly entries: ContinuationAuditEntry[] = [];
	readonly handlers = new Map<string, Handler[]>();
	readOnly = false;

	on(event: string, handler: Handler): void {
		const existing = this.handlers.get(event) ?? [];
		existing.push(handler);
		this.handlers.set(event, existing);
	}

	sendMessage(
		message: { customType: string; content: string; display: boolean },
		options: { deliverAs: string },
	): void {
		this.sent.push({ ...message, deliverAs: options.deliverAs });
	}

	appendEntry(_type: string, entry: ContinuationAuditEntry): void {
		this.entries.push(entry);
	}

	getFlag(name: string): unknown {
		return name === "read-only" ? this.readOnly : undefined;
	}

	async fire(event: string, payload: unknown, ctx: ExtensionContext): Promise<void> {
		for (const handler of this.handlers.get(event) ?? []) await handler(payload, ctx);
	}
}

export function runtime(goal: string | null = "Ship the guard"): TasksRuntime {
	return {
		state: { goal, tasks: [{ label: "Implement", description: "d", criteria: "c", status: "active", review: null }] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget() {},
		persistState() {},
	} as unknown as TasksRuntime;
}

export const assistantStop = {
	messages: [{ role: "assistant", content: [{ type: "text", text: "Let me check the wiring." }] }],
};

export const verdict: ContinuationVerdict = {
	retrigger: true,
	category: "I",
	reason: "announced a next step it never took",
};

export function context(
	overrides: Partial<{
		hasUI: boolean;
		pending: boolean;
		pendingAfterJudge: boolean;
		signal: AbortSignal;
		notify: (m: string) => void;
	}> = {},
) {
	const notifications: string[] = [];
	let reads = 0;
	const ctx = {
		hasUI: overrides.hasUI ?? true,
		signal: overrides.signal,
		// The guard samples this twice; the second read models input arriving mid-judge.
		hasPendingMessages: () => {
			reads += 1;
			if (reads > 1 && overrides.pendingAfterJudge) return true;
			return overrides.pending ?? false;
		},
		sessionManager: { getEntries: () => [] },
		ui: {
			notify: (message: string) => {
				if (overrides.notify) return overrides.notify(message);
				notifications.push(message);
			},
		},
	} as unknown as ExtensionContext;
	return { ctx, notifications };
}

export function setup(deps: Partial<ContinuationGuardDeps> = {}, tasks: TasksRuntime = runtime()) {
	const pi = new FakePi();
	const judged: unknown[] = [];
	registerContinuationGuard(pi as unknown as ExtensionAPI, tasks, {
		planHandoffActive: () => false,
		isSubagentRun: () => false,
		resolveModel: async () => ({ model: { id: "haiku" } as any, auth: { apiKey: "k" } }),
		judge: async (args) => {
			judged.push(args.context);
			return verdict;
		},
		...deps,
	});
	return { pi, judged };
}
