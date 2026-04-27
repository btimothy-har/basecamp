/**
 * Async agent notification — delivers completed background agent results
 * to the LLM conversation via pi.sendMessage().
 *
 * Listens for AGENT_ASYNC_COMPLETE_EVENT on the EventBus and formats the
 * result into a message that triggers a new LLM turn.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { AGENT_ASYNC_COMPLETE_EVENT, type AsyncResult } from "./types.ts";

const SEEN_TTL_MS = 10 * 60 * 1000;
const seen = new Map<string, number>();

function isDuplicate(runId: string): boolean {
	const now = Date.now();

	// Prune expired entries
	for (const [key, ts] of seen) {
		if (now - ts > SEEN_TTL_MS) seen.delete(key);
	}

	if (seen.has(runId)) return true;
	seen.set(runId, now);
	return false;
}

function formatDuration(ms: number): string {
	if (ms < 1000) return `${ms}ms`;
	if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
	const minutes = Math.floor(ms / 60_000);
	const seconds = Math.floor((ms % 60_000) / 1000);
	return `${minutes}m${seconds}s`;
}

function formatResult(result: AsyncResult): string {
	const status = result.success ? "completed" : "failed";
	const duration = formatDuration(result.durationMs);

	const lines = [`Background agent ${status}: **${result.agent}** (${duration})`, ""];

	if (result.error) {
		lines.push(`**Error:** ${result.error}`, "");
	}

	if (result.output) {
		lines.push(result.output);
	} else {
		lines.push("(no output)");
	}

	return lines.join("\n");
}

export function registerAsyncNotify(pi: ExtensionAPI): void {
	pi.events.on(AGENT_ASYNC_COMPLETE_EVENT, (data: unknown) => {
		const result = data as AsyncResult;
		if (!result.runId) return;
		if (isDuplicate(result.runId)) return;

		pi.sendMessage(
			{
				customType: "agent-async-result",
				content: formatResult(result),
				display: true,
			},
			{ triggerTurn: true },
		);
	});
}
