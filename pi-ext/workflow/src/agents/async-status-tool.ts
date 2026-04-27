/**
 * agent_status tool — non-blocking snapshot of background async agents.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";
import type { AsyncWatcherState } from "./async-watcher.ts";
import { getAllJobs } from "./async-watcher.ts";

function formatDuration(ms: number): string {
	if (ms < 1000) return `${ms}ms`;
	if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
	const minutes = Math.floor(ms / 60_000);
	const seconds = Math.floor((ms % 60_000) / 1000);
	return `${minutes}m${seconds}s`;
}

export function registerAgentStatusTool(pi: ExtensionAPI, state: AsyncWatcherState): void {
	pi.registerTool({
		name: "agent_status",
		label: "Agent Status",
		description: "Check status of background async agents. Returns current state of all tracked background agents.",
		promptSnippet: "Check background agent status (non-blocking)",

		parameters: Type.Object({
			id: Type.Optional(Type.String({ description: "Specific async agent ID to check" })),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
			const jobs = params.id ? getAllJobs(state).filter((j) => j.asyncId === params.id) : getAllJobs(state);

			if (jobs.length === 0) {
				const msg = params.id ? `No background agent found with ID "${params.id}"` : "No background agents tracked.";
				return { content: [{ type: "text", text: msg }], details: undefined };
			}

			const lines: string[] = [`Background agents: ${jobs.length}`, ""];
			for (const job of jobs) {
				const elapsed = formatDuration(Date.now() - job.startedAt);
				const parts = [`- **${job.agent}** [${job.asyncId}]: ${job.status}`];
				parts.push(`(${elapsed})`);
				if (job.model) parts.push(`model=${job.model}`);
				if (job.toolCount) parts.push(`${job.toolCount} tools`);
				if (job.turnCount) parts.push(`${job.turnCount} turns`);
				lines.push(parts.join(" "));

				const taskPreview = job.task.length > 80 ? `${job.task.slice(0, 80)}...` : job.task;
				lines.push(`  Task: ${taskPreview}`);
			}

			return { content: [{ type: "text", text: lines.join("\n") }], details: undefined };
		},

		renderCall(args, theme, _context) {
			const label = args.id ? `agent_status ${args.id}` : "agent_status";
			return new Text(theme.fg("toolTitle", theme.bold(label)), 0, 0);
		},

		renderResult(result, _options, theme, _context) {
			const text = result.content[0];
			const content = text?.type === "text" ? text.text : "(no data)";
			return new Text(theme.fg("dim", content), 0, 0);
		},
	});
}
