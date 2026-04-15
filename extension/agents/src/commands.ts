/**
 * Slash commands for agent browsing within pi.
 *
 * /agents  — interactive agent browser (select → detail view)
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { AgentConfig } from "./types.ts";

function formatAgentDetail(agent: AgentConfig): string {
  const lines: string[] = [
    `# ${agent.name}`,
    "",
    agent.description,
    "",
    `**Source:** ${agent.source} — \`${agent.filePath}\``,
  ];

  lines.push(`**Model:** ${agent.model}`);
  if (agent.thinking) lines.push(`**Thinking:** ${agent.thinking}`);
  if (agent.tools) lines.push(`**Tools:** ${agent.tools.join(", ")}`);
  if (agent.skills) lines.push(`**Skills:** ${agent.skills.join(", ")}`);

  if (agent.systemPrompt) {
    lines.push("", "## System Prompt", "");
    // Show first ~2000 chars to avoid overwhelming the UI
    const preview =
      agent.systemPrompt.length > 2000
        ? agent.systemPrompt.slice(0, 2000) + "\n\n[truncated]"
        : agent.systemPrompt;
    lines.push(preview);
  }

  return lines.join("\n");
}

export function registerAgentCommands(
  pi: ExtensionAPI,
  getAgents: () => AgentConfig[],
): void {
  // /agents — browse agent definitions
  pi.registerCommand("agents", {
    description: "Browse available agent definitions",
    handler: async (_args, ctx) => {
      const agents = getAgents();
      if (agents.length === 0) {
        ctx.ui.notify("No agents found.", "info");
        return;
      }

      const badges: Record<string, string> = {
        builtin: "builtin",
        user: "user",
        project: "project",
      };

      const labels = agents.map((a) => {
        const badge = badges[a.source] ?? a.source;
        return `${a.name} [${badge}] — ${a.description}`;
      });

      const choice = await ctx.ui.select("Agents", labels);
      if (choice === undefined) return;

      const idx = labels.indexOf(choice);
      const agent = agents[idx];
      if (!agent) return;

      ctx.ui.notify(formatAgentDetail(agent), "info");
    },
  });

}
