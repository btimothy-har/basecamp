/**
 * Agent tool — registered as a pi tool the LLM calls to dispatch subagents.
 *
 * Subagents run synchronously as child processes. The subagent's output
 * is returned as the tool result so the parent LLM can reason about it.
 *
 * Includes:
 *   - Status line updates (option A)
 *   - Custom renderCall/renderResult (option D)
 *
 * Usage:
 *   { agent: "scout", task: "..." }              → run named agent
 *   { task: "Fix the bug" }                      → ad-hoc (no agent definition)
 */

import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { getMarkdownTheme } from "@mariozechner/pi-coding-agent";
import { Container, Markdown, Spacer, Text } from "@mariozechner/pi-tui";
import type { AgentConfig, ModelStrategy, AgentDetails, ToolCallRecord } from "./types.ts";
import { AgentToolParams, DEFAULT_AGENT_MAX_DEPTH } from "./types.ts";
import { spawnAgent } from "./executor.ts";

// ============================================================================
// Model Resolution
// ============================================================================

function resolveModel(
  strategy: ModelStrategy,
  toolOverride: string | undefined,
  parentModel: string | undefined,
): string | undefined {
  switch (strategy) {
    case "default":
      return undefined;
    case "inherit":
      return toolOverride ?? parentModel;
    default:
      return strategy;
  }
}

// ============================================================================
// Depth Guard
// ============================================================================

function checkDepth(): void {
  const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
  const max = Number(
    process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH,
  );
  if (depth >= max) {
    throw new Error(
      `Agent nesting blocked (depth=${depth}, max=${max}). ` +
        "Complete your task directly without spawning further agents.",
    );
  }
}

// ============================================================================
// Agent Environment
// ============================================================================

function buildAgentEnv(opts: {
  name: string;
  parentSession: string;
  project: string;
}): Record<string, string> {
  const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("BASECAMP_") && v !== undefined) {
      env[k] = v;
    }
  }
  env.BASECAMP_PROJECT = opts.project;
  env.BASECAMP_PARENT_SESSION = opts.parentSession;
  env.BASECAMP_AGENT_DEPTH = String(depth + 1);
  env.BASECAMP_AGENT_MAX_DEPTH =
    process.env.BASECAMP_AGENT_MAX_DEPTH ?? String(DEFAULT_AGENT_MAX_DEPTH);
  return env;
}

// ============================================================================
// Formatting Helpers
// ============================================================================

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  return `${minutes}m${seconds}s`;
}

function formatTokens(count: number): string {
  if (count < 1000) return count.toString();
  if (count < 10_000) return `${(count / 1000).toFixed(1)}k`;
  return `${Math.round(count / 1000)}k`;
}

function shortenPath(p: string): string {
  const home = os.homedir();
  return p.startsWith(home) ? `~${p.slice(home.length)}` : p;
}

function formatToolCallLine(
  tc: ToolCallRecord,
  fg: (color: string, text: string) => string,
): string {
  switch (tc.name) {
    case "bash": {
      const cmd = (tc.args.command as string) || "...";
      const preview = cmd.length > 60 ? `${cmd.slice(0, 60)}...` : cmd;
      return fg("muted", "$ ") + fg("toolOutput", preview);
    }
    case "read": {
      const raw = (tc.args.file_path || tc.args.path || "...") as string;
      const offset = tc.args.offset as number | undefined;
      const limit = tc.args.limit as number | undefined;
      let text = fg("accent", shortenPath(raw));
      if (offset !== undefined || limit !== undefined) {
        const start = offset ?? 1;
        const end = limit !== undefined ? start + limit - 1 : "";
        text += fg("warning", `:${start}${end ? `-${end}` : ""}`);
      }
      return fg("muted", "read ") + text;
    }
    case "write": {
      const raw = (tc.args.file_path || tc.args.path || "...") as string;
      return fg("muted", "write ") + fg("accent", shortenPath(raw));
    }
    case "edit": {
      const raw = (tc.args.file_path || tc.args.path || "...") as string;
      return fg("muted", "edit ") + fg("accent", shortenPath(raw));
    }
    case "grep": {
      const pattern = (tc.args.pattern || "") as string;
      const raw = (tc.args.path || ".") as string;
      return fg("muted", "grep ") + fg("accent", `/${pattern}/`) + fg("dim", ` in ${shortenPath(raw)}`);
    }
    case "find": {
      const pattern = (tc.args.pattern || "*") as string;
      const raw = (tc.args.path || ".") as string;
      return fg("muted", "find ") + fg("accent", pattern) + fg("dim", ` in ${shortenPath(raw)}`);
    }
    case "ls": {
      const raw = (tc.args.path || ".") as string;
      return fg("muted", "ls ") + fg("accent", shortenPath(raw));
    }
    default: {
      const argsStr = JSON.stringify(tc.args);
      const preview = argsStr.length > 50 ? `${argsStr.slice(0, 50)}...` : argsStr;
      return fg("accent", tc.name) + fg("dim", ` ${preview}`);
    }
  }
}

function formatUsageLine(
  usage: { input: number; output: number; cacheRead: number; cost: number; turns: number },
  model?: string,
  durationMs?: number,
): string {
  const parts: string[] = [];
  if (usage.turns) parts.push(`${usage.turns} turn${usage.turns > 1 ? "s" : ""}`);
  if (durationMs !== undefined) parts.push(formatDuration(durationMs));
  if (usage.input) parts.push(`↑${formatTokens(usage.input)}`);
  if (usage.output) parts.push(`↓${formatTokens(usage.output)}`);
  if (usage.cacheRead) parts.push(`R${formatTokens(usage.cacheRead)}`);
  if (usage.cost) parts.push(`$${usage.cost.toFixed(4)}`);
  if (model) parts.push(model);
  return parts.join(" ");
}

// ============================================================================
// Status Line
// ============================================================================

const STATUS_KEY = "basecamp-agent";
const COLLAPSED_TOOL_COUNT = 10;

function setStatusIdle(ctx: ExtensionContext, agentCount: number): void {
  if (!ctx.hasUI) return;
  const t = ctx.ui.theme;
  ctx.ui.setStatus(STATUS_KEY, t.fg("dim", `🤖 ${agentCount} agents`));
}

function setStatusRunning(ctx: ExtensionContext, agentName: string): void {
  if (!ctx.hasUI) return;
  const t = ctx.ui.theme;
  ctx.ui.setStatus(STATUS_KEY,
    t.fg("accent", "⏳") + t.fg("dim", ` ${agentName}...`),
  );
}

function setStatusDone(ctx: ExtensionContext, agentName: string, durationMs: number, ok: boolean): void {
  if (!ctx.hasUI) return;
  const t = ctx.ui.theme;
  const icon = ok ? t.fg("success", "✅") : t.fg("error", "❌");
  ctx.ui.setStatus(STATUS_KEY,
    icon + t.fg("dim", ` ${agentName} ${formatDuration(durationMs)}`),
  );
}

// ============================================================================
// Tool Registration
// ============================================================================

export function registerAgentTool(
  pi: ExtensionAPI,
  getAgents: () => AgentConfig[],
  getSessionName: () => string,
): void {
  pi.registerTool({
    name: "agent",
    label: "Agent",
    description: `Dispatch a subagent to perform a task synchronously. The subagent runs as a child process and its output is returned as the tool result.

DISPATCH: { agent: "scout", task: "Investigate the auth module" }
AD-HOC: { task: "Fix the login bug" }

Available agents are discovered from project (.basecamp/agents/), user (~/.basecamp/agents/), and builtin definitions.`,

    promptSnippet:
      "Dispatch a subagent (runs synchronously, returns output)",

    parameters: AgentToolParams,

    // ------------------------------------------------------------------
    // Execute
    // ------------------------------------------------------------------

    async execute(_id, params, signal, _onUpdate, ctx) {
      try {
        checkDepth();
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return { content: [{ type: "text", text: msg }], isError: true };
      }

      // Resolve agent config
      const agents = getAgents();
      let agentConfig: AgentConfig | null = null;
      if (params.agent) {
        agentConfig = agents.find((a) => a.name === params.agent) ?? null;
        if (!agentConfig) {
          const available = agents.map((a) => a.name).join(", ") || "none";
          return {
            content: [{ type: "text", text: `Unknown agent: ${params.agent}. Available: ${available}` }],
            isError: true,
          };
        }
      }

      // Resolve parameters
      const model = resolveModel(
        agentConfig?.model ?? "inherit",
        params.model,
        ctx.model?.id,
      );
      const prefix = `agent-${randomUUID().slice(0, 6)}`;
      const name = params.name ? `${prefix}-${params.name}` : prefix;
      const project = process.env.BASECAMP_PROJECT ?? "default";
      const sessionDir = path.join(os.tmpdir(), "basecamp-agents", name, "session");
      const parentSession = getSessionName();
      const env = buildAgentEnv({ name, parentSession, project });
      const agentLabel = params.agent ?? "ad-hoc";

      // Status line: running
      setStatusRunning(ctx, agentLabel);

      try {
        let result = await spawnAgent(
          agentConfig,
          params.task,
          { name, model, cwd: ctx.cwd, env, sessionDir },
          signal,
        );

        // Retry with default model if the requested model wasn't found
        if (
          result.exitCode === 1 &&
          model &&
          result.error?.includes("not found") &&
          result.usage.turns === 0
        ) {
          if (ctx.hasUI) {
            ctx.ui.notify(
              `Model "${model}" not found — retrying with default model`,
              "warning",
            );
          }
          const retrySessionDir = sessionDir + "-retry";
          fs.mkdirSync(retrySessionDir, { recursive: true });
          result = await spawnAgent(
            agentConfig,
            params.task,
            { name, model: undefined, cwd: ctx.cwd, env, sessionDir: retrySessionDir },
            signal,
          );
        }

        const ok = result.exitCode === 0;

        // Status line: done
        setStatusDone(ctx, agentLabel, result.durationMs, ok);

        // Build structured details for renderResult
        const details: AgentDetails = {
          agent: agentLabel,
          agentSource: agentConfig?.source ?? "ad-hoc",
          task: params.task,
          exitCode: result.exitCode,
          output: result.output,
          error: result.error,
          model: result.model ?? (model ? model : undefined),
          toolCalls: result.toolCalls,
          usage: result.usage,
          durationMs: result.durationMs,
        };

        // Build text content for the LLM (it doesn't see renderResult)
        const modelLabel = details.model ?? "default";
        const header = `**${agentLabel}** (${modelLabel}) — ${formatDuration(result.durationMs)}, ${result.usage.turns} turn(s)`;

        if (!ok) {
          const errorDetail = result.error ?? "Agent failed with no output";
          const textContent = result.output
            ? `${header}\n\n${result.output}\n\n**Error:** ${errorDetail}`
            : `${header}\n\n**Error:** ${errorDetail}`;
          return {
            content: [{ type: "text", text: textContent }],
            details,
            isError: true,
          };
        }

        const textContent = result.output
          ? `${header}\n\n${result.output}`
          : `${header}\n\n(no output)`;

        return {
          content: [{ type: "text", text: textContent }],
          details,
        };
      } catch (error) {
        setStatusDone(ctx, agentLabel, 0, false);
        const msg = error instanceof Error ? error.message : String(error);
        return { content: [{ type: "text", text: msg }], isError: true };
      }
    },

    // ------------------------------------------------------------------
    // renderCall — compact display of the tool invocation
    // ------------------------------------------------------------------

    renderCall(args, theme, _context) {
      const agentName = args.agent || "ad-hoc";
      const task = args.task || "...";
      const preview = task.length > 70 ? `${task.slice(0, 70)}...` : task;

      let text = theme.fg("toolTitle", theme.bold("agent ")) + theme.fg("accent", agentName);
      if (args.model) text += theme.fg("dim", ` (${args.model})`);
      text += `\n  ${theme.fg("dim", preview)}`;
      return new Text(text, 0, 0);
    },

    // ------------------------------------------------------------------
    // renderResult — rich display of the subagent's activity and output
    // ------------------------------------------------------------------

    renderResult(result, { expanded }, theme, _context) {
      const details = result.details as AgentDetails | undefined;

      if (!details) {
        const text = result.content[0];
        return new Text(text?.type === "text" ? text.text : "(no output)", 0, 0);
      }

      const fg = theme.fg.bind(theme);
      const isError = details.exitCode !== 0;
      const icon = isError ? fg("error", "✗") : fg("success", "✓");
      const sourceLabel = details.agentSource !== "ad-hoc" ? fg("muted", ` (${details.agentSource})`) : "";

      // --- Expanded view ---
      if (expanded) {
        const mdTheme = getMarkdownTheme();
        const container = new Container();

        // Header
        let header = `${icon} ${fg("toolTitle", theme.bold(details.agent))}${sourceLabel}`;
        if (isError && details.error) header += ` ${fg("error", `[failed]`)}`;
        container.addChild(new Text(header, 0, 0));

        // Error detail
        if (isError && details.error) {
          container.addChild(new Text(fg("error", `Error: ${details.error}`), 0, 0));
        }

        // Task
        container.addChild(new Spacer(1));
        container.addChild(new Text(fg("muted", "─── Task ───"), 0, 0));
        container.addChild(new Text(fg("dim", details.task), 0, 0));

        // Tool calls
        if (details.toolCalls.length > 0) {
          container.addChild(new Spacer(1));
          container.addChild(new Text(fg("muted", `─── Tools (${details.toolCalls.length}) ───`), 0, 0));
          for (const tc of details.toolCalls) {
            container.addChild(new Text(fg("muted", "→ ") + formatToolCallLine(tc, fg), 0, 0));
          }
        }

        // Output as markdown
        container.addChild(new Spacer(1));
        container.addChild(new Text(fg("muted", "─── Output ───"), 0, 0));
        if (details.output) {
          container.addChild(new Markdown(details.output.trim(), 0, 0, mdTheme));
        } else {
          container.addChild(new Text(fg("muted", "(no output)"), 0, 0));
        }

        // Usage stats
        const usageLine = formatUsageLine(details.usage, details.model, details.durationMs);
        if (usageLine) {
          container.addChild(new Spacer(1));
          container.addChild(new Text(fg("dim", usageLine), 0, 0));
        }

        return container;
      }

      // --- Collapsed view ---
      let text = `${icon} ${fg("toolTitle", theme.bold(details.agent))}${sourceLabel}`;
      if (isError && details.error) {
        text += `\n${fg("error", `Error: ${details.error}`)}`;
      }

      // Tool calls (collapsed: show last N)
      if (details.toolCalls.length > 0) {
        const toShow = details.toolCalls.slice(-COLLAPSED_TOOL_COUNT);
        const skipped = details.toolCalls.length - toShow.length;
        if (skipped > 0) text += `\n${fg("muted", `... ${skipped} earlier tools`)}`;
        for (const tc of toShow) {
          text += `\n${fg("muted", "→ ") + formatToolCallLine(tc, fg)}`;
        }
      }

      // Output preview (first 3 lines)
      if (details.output) {
        const preview = details.output.split("\n").slice(0, 3).join("\n");
        text += `\n${fg("toolOutput", preview)}`;
        if (details.output.split("\n").length > 3) {
          text += `\n${fg("muted", "...")}`;
        }
      } else if (!isError) {
        text += `\n${fg("muted", "(no output)")}`;
      }

      // Usage stats
      const usageLine = formatUsageLine(details.usage, details.model, details.durationMs);
      if (usageLine) text += `\n${fg("dim", usageLine)}`;

      text += `\n${fg("muted", "(Ctrl+O to expand)")}`;
      return new Text(text, 0, 0);
    },
  });
}

// Re-export status helpers for use in index.ts
export { setStatusIdle };
