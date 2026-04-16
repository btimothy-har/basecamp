/**
 * Slash commands for agent browsing within pi.
 *
 * /agents  — interactive agent browser (select → detail overlay)
 */

import type { ExtensionAPI, ExtensionCommandContext } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getMarkdownTheme } from "@mariozechner/pi-coding-agent";
import { Container, Markdown, matchesKey, Spacer, Text } from "@mariozechner/pi-tui";
import type { AgentConfig } from "./types.ts";

// ============================================================================
// Detail Overlay
// ============================================================================

function buildDetailMarkdown(agent: AgentConfig): string {
	const meta: string[] = [];
	meta.push(`| Field | Value |`);
	meta.push(`|-------|-------|`);
	meta.push(`| **Source** | ${agent.source} |`);
	meta.push(`| **Model** | \`${agent.model}\` |`);
	if (agent.thinking) meta.push(`| **Thinking** | ${agent.thinking} |`);
	if (agent.tools) meta.push(`| **Tools** | ${agent.tools.join(", ")} |`);
	if (agent.skills) meta.push(`| **Skills** | ${agent.skills.join(", ")} |`);

	const sections = [agent.description, "", ...meta];

	if (agent.systemPrompt) {
		const preview =
			agent.systemPrompt.length > 3000 ? `${agent.systemPrompt.slice(0, 3000)}\n\n*[truncated]*` : agent.systemPrompt;
		sections.push("", "---", "", preview);
	}

	return sections.join("\n");
}

async function showAgentDetail(agent: AgentConfig, ctx: ExtensionCommandContext): Promise<void> {
	if (!ctx.hasUI) return;

	await ctx.ui.custom((_tui, theme, _kb, done) => {
		const container = new Container();
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const mdTheme = getMarkdownTheme();

		container.addChild(border);
		container.addChild(new Text(theme.fg("accent", theme.bold(agent.name)), 1, 0));
		container.addChild(new Spacer(1));
		container.addChild(new Markdown(buildDetailMarkdown(agent), 1, 0, mdTheme));
		container.addChild(new Spacer(1));
		container.addChild(new Text(theme.fg("dim", "Esc to close"), 1, 0));
		container.addChild(border);

		return {
			render: (width: number) => container.render(width),
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape") || matchesKey(data, "enter")) {
					done(undefined);
				}
			},
		};
	});
}

// ============================================================================
// Select List
// ============================================================================

function buildSelectLabel(agent: AgentConfig): string {
	const source = agent.source === "builtin" ? "" : ` (${agent.source})`;
	return `${agent.name}${source} — ${agent.description}`;
}

// ============================================================================
// Command Registration
// ============================================================================

export function registerAgentCommands(pi: ExtensionAPI, getAgents: () => AgentConfig[]): void {
	pi.registerCommand("agents", {
		description: "Browse available agent definitions",
		handler: async (_args, ctx) => {
			const agents = getAgents();
			if (agents.length === 0) {
				ctx.ui.notify("No agents found.", "info");
				return;
			}

			const labels = agents.map(buildSelectLabel);

			const choice = await ctx.ui.select("Agents", labels);
			if (choice === undefined) return;

			const idx = labels.indexOf(choice);
			const agent = agents[idx];
			if (!agent) return;

			await showAgentDetail(agent, ctx);
		},
	});
}
