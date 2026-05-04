/**
 * Slash commands for agent browsing within pi.
 *
 * /agents  — interactive agent browser (two-line list → detail overlay)
 */

import type { ExtensionAPI, ExtensionCommandContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getMarkdownTheme } from "@mariozechner/pi-coding-agent";
import { Container, Markdown, matchesKey, Spacer, Text } from "@mariozechner/pi-tui";
import { type AgentConfig, getAgentToolAllowlist } from "./types.ts";

// ============================================================================
// Agent List (two-line select)
// ============================================================================

function renderAgentList(agents: AgentConfig[], selectedIdx: number, width: number, theme: Theme): string[] {
	const lines: string[] = [];
	const innerWidth = width - 4; // 2 for marker + 2 padding

	for (let i = 0; i < agents.length; i++) {
		const agent = agents[i]!;
		const isSelected = i === selectedIdx;
		const marker = isSelected ? theme.fg("accent", "▸ ") : "  ";

		// Line 1: name (left) + source (right)
		const name = isSelected ? theme.fg("accent", theme.bold(agent.name)) : theme.fg("toolTitle", agent.name);
		const source = theme.fg("dim", agent.source);
		const nameLen = agent.name.length;
		const sourceLen = agent.source.length;
		const gap = Math.max(1, innerWidth - nameLen - sourceLen);
		const line1 = `${marker}${name}${" ".repeat(gap)}${source}`;

		// Line 2: description (indented, dimmed, truncated)
		const maxDesc = innerWidth - 2;
		const desc = agent.description.length > maxDesc ? `${agent.description.slice(0, maxDesc - 1)}…` : agent.description;
		const line2 = `  ${theme.fg("dim", `  ${desc}`)}`;

		lines.push(line1, line2);

		// Blank line between items (except after last)
		if (i < agents.length - 1) lines.push("");
	}

	return lines;
}

async function showAgentList(agents: AgentConfig[], ctx: ExtensionCommandContext): Promise<AgentConfig | undefined> {
	if (!ctx.hasUI) return undefined;

	return ctx.ui.custom<AgentConfig | undefined>((_tui, theme, _kb, done) => {
		let selected = 0;

		const header = new Text(theme.fg("accent", theme.bold("Agents")), 1, 0);
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const hint = new Text(theme.fg("dim", "↑↓ navigate  Enter select  Esc cancel"), 1, 0);
		const listText = new Text("", 0, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(listText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const listLines = renderAgentList(agents, selected, width, theme);
				listText.setText(listLines.join("\n"));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape")) {
					done(undefined);
				} else if (matchesKey(data, "enter")) {
					done(agents[selected]);
				} else if (matchesKey(data, "up")) {
					if (selected > 0) {
						selected--;
						container.invalidate();
					}
				} else if (matchesKey(data, "down")) {
					if (selected < agents.length - 1) {
						selected++;
						container.invalidate();
					}
				}
			},
		};
	});
}

// ============================================================================
// Detail Overlay
// ============================================================================

function buildDetailMarkdown(agent: AgentConfig): string {
	const meta: string[] = [];
	meta.push("| Field | Value |");
	meta.push("|-------|-------|");
	meta.push(`| **Source** | ${agent.source} |`);
	meta.push(`| **Model** | \`${agent.model}\` |`);
	if (agent.thinking) meta.push(`| **Thinking** | ${agent.thinking} |`);
	meta.push(`| **Tools** | ${getAgentToolAllowlist(agent).join(", ")} |`);
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

			const agent = await showAgentList(agents, ctx);
			if (!agent) return;

			await showAgentDetail(agent, ctx);
		},
	});
}
