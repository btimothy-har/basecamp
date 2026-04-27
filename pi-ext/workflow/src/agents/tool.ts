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
 *   { agent: "scout", task: "..." }                    → run named agent
 *   { task: "Fix the bug" }                      → ad-hoc (no agent definition)
 */

import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { getMarkdownTheme } from "@mariozechner/pi-coding-agent";
import { type Component, Container, Markdown, Spacer, Text } from "@mariozechner/pi-tui";
import { resolveModelAlias } from "../../../platform/config.ts";
import { hasInvokedSkill } from "../../../platform/skill-tracker";
import { formatTaskProgressSummary, renderCompactTaskProgressLines } from "../tasks/render";
import type { AgentStreamEvent } from "./executor.ts";
import { spawnAgent } from "./executor.ts";
import type { AgentConfig, AgentDetails, AgentPartialDetails, ModelStrategy, ToolCallRecord } from "./types.ts";
import { AgentToolParams, DEFAULT_AGENT_MAX_DEPTH } from "./types.ts";

// ============================================================================
// Model Resolution
// ============================================================================

interface ParentModel {
	id: string;
	provider: string;
}

function resolveModel(strategy: ModelStrategy, parentModel: ParentModel | undefined): string | undefined {
	switch (strategy) {
		case "default":
			return undefined;
		case "inherit":
			if (!parentModel) return undefined;
			// Provider-qualify to avoid ambiguous resolution across providers
			return `${parentModel.provider}/${parentModel.id}`;
		default:
			return resolveModelAlias(strategy);
	}
}

// ============================================================================
// Depth Guard
// ============================================================================

function checkDepth(): void {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const max = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
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

function buildAgentEnv(opts: { name: string; parentSession: string; project: string }): Record<string, string> {
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
	env.BASECAMP_AGENT_MAX_DEPTH = process.env.BASECAMP_AGENT_MAX_DEPTH ?? String(DEFAULT_AGENT_MAX_DEPTH);
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

type ThemeColor = Parameters<import("@mariozechner/pi-coding-agent").Theme["fg"]>[0];

function formatToolCallLine(tc: ToolCallRecord, fg: (color: ThemeColor, text: string) => string): string {
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

const COLLAPSED_TOOL_COUNT = 3;
const COLLAPSED_MESSAGE_LINES = 2;

// Each concurrent agent gets its own status key so they don't clobber each other.
function statusKey(id: string): string {
	return `basecamp-agent-${id}`;
}

function setStatusRunning(
	ctx: ExtensionContext,
	id: string,
	agentName: string,
	toolCount: number,
	turnCount: number,
): void {
	if (!ctx.hasUI) return;
	const t = ctx.ui.theme;
	const parts = [t.fg("accent", "⏳"), t.fg("dim", ` ${agentName}`)];
	if (toolCount > 0) parts.push(t.fg("muted", ` — ${toolCount} tool${toolCount > 1 ? "s" : ""}`));
	if (turnCount > 0) parts.push(t.fg("muted", `, turn ${turnCount}`));
	parts.push(t.fg("dim", "..."));
	ctx.ui.setStatus(statusKey(id), parts.join(""));
}

function clearStatus(ctx: ExtensionContext, id: string): void {
	if (!ctx.hasUI) return;
	ctx.ui.setStatus(statusKey(id), undefined);
}

// ============================================================================
// Partial (In-Progress) View
// ============================================================================

function renderPartialView(
	partial: AgentPartialDetails,
	fg: (color: ThemeColor, text: string) => string,
	theme: import("@mariozechner/pi-coding-agent").Theme,
): Component {
	const sourceLabel = partial.agentSource !== "ad-hoc" ? fg("muted", ` (${partial.agentSource})`) : "";
	const modelLabel = partial.model ? fg("muted", ` (${partial.model})`) : "";

	const statParts: string[] = [];
	if (partial.toolCalls.length > 0)
		statParts.push(`${partial.toolCalls.length} tool${partial.toolCalls.length > 1 ? "s" : ""}`);
	if (partial.turnCount > 0) statParts.push(`turn ${partial.turnCount}`);
	const stats = statParts.length > 0 ? fg("dim", ` \u2014 ${statParts.join(", ")}`) : "";

	let text = `${fg("accent", "\u23f3")} ${fg("toolTitle", theme.bold(partial.agent))}${sourceLabel}${modelLabel}${stats}`;

	if (partial.taskProgress) {
		const taskLines = renderCompactTaskProgressLines(partial.taskProgress, { fg });
		if (taskLines.length > 0) {
			text += `\n\n${taskLines.map((line) => `  ${line}`).join("\n")}`;
		}
	}

	// Last N tool calls (scrolling window)
	if (partial.toolCalls.length > 0) {
		if (partial.taskProgress) text += `\n${fg("muted", "  Tools")}`;
		const toShow = partial.toolCalls.slice(-COLLAPSED_TOOL_COUNT);
		const skipped = partial.toolCalls.length - toShow.length;
		if (skipped > 0) text += `\n${fg("muted", `  ... ${skipped} earlier`)}`;
		for (const tc of toShow) {
			text += `\n${fg("muted", "  \u2192 ") + formatToolCallLine(tc, fg)}`;
		}
	}

	// Last N lines of the latest assistant message
	if (partial.latestMessage) {
		const lines = partial.latestMessage.trim().split("\n").filter(Boolean);
		const messageLines = lines.slice(-COLLAPSED_MESSAGE_LINES);
		for (const line of messageLines) {
			text += `\n${fg("dim", `  ${line}`)}`;
		}
	}

	return new Text(text, 0, 0);
}

// ============================================================================
// Tool Registration
// ============================================================================

const BASECAMP_EXTENSION_ROOT = fs.realpathSync(
	path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", ".."),
);
const SUBAGENT_EXCLUDED_EXTENSION_TOOLS = new Set(["escalate", "pr_publish"]);

type ToolInfo = ReturnType<ExtensionAPI["getAllTools"]>[number];

function resolveToolSourcePath(value: string | undefined): string | null {
	if (!value || value.startsWith("<")) return null;
	try {
		return fs.realpathSync(value);
	} catch {
		return path.resolve(value);
	}
}

function isWithinBasecampExtensionRoot(value: string | undefined): boolean {
	const sourcePath = resolveToolSourcePath(value);
	if (!sourcePath) return false;
	const relative = path.relative(BASECAMP_EXTENSION_ROOT, sourcePath);
	return relative === "" || (relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function isBasecampExtensionTool(tool: ToolInfo): boolean {
	if (tool.sourceInfo.source === "builtin" || tool.sourceInfo.source === "sdk") return false;
	return isWithinBasecampExtensionRoot(tool.sourceInfo.baseDir) || isWithinBasecampExtensionRoot(tool.sourceInfo.path);
}

function getBasecampExtensionToolNames(pi: ExtensionAPI): string[] {
	return pi
		.getAllTools()
		.filter((tool) => isBasecampExtensionTool(tool) && !SUBAGENT_EXCLUDED_EXTENSION_TOOLS.has(tool.name))
		.map((tool) => tool.name);
}

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

Available agents are discovered from user (~/.pi/agents/) and builtin definitions.`,

		promptSnippet: "Dispatch a subagent (runs synchronously, returns output)",

		parameters: AgentToolParams,

		// ------------------------------------------------------------------
		// Execute
		// ------------------------------------------------------------------

		async execute(_id, params, signal, onUpdate, ctx) {
			try {
				checkDepth();
				if (!hasInvokedSkill("agents")) {
					throw new Error('Load the agents skill first: call skill({ name: "agents" }) before dispatching.');
				}
			} catch (error) {
				const msg = error instanceof Error ? error.message : String(error);
				return { content: [{ type: "text", text: msg }], isError: true, details: null as unknown as AgentDetails };
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
						details: null as unknown as AgentDetails,
					};
				}
			}

			// Resolve parameters
			const model = resolveModel(agentConfig?.model ?? "inherit", ctx.model);
			const agentId = randomUUID().slice(0, 6);
			const prefix = `agent-${agentId}`;
			const name = params.name ? `${prefix}-${params.name}` : prefix;
			const project = process.env.BASECAMP_PROJECT ?? "default";
			const sessionDir = path.join(os.tmpdir(), "basecamp-agents", name, "session");
			const parentSession = getSessionName();
			const env = buildAgentEnv({ name, parentSession, project });
			const agentLabel = params.agent ?? "ad-hoc";
			const extensionTools = getBasecampExtensionToolNames(pi);

			// Progressive rendering state
			const partial: AgentPartialDetails = {
				agent: agentLabel,
				agentSource: agentConfig?.source ?? "ad-hoc",
				model: model ?? undefined,
				toolCalls: [],
				turnCount: 0,
			};

			const emitUpdate = () => {
				setStatusRunning(ctx, agentId, agentLabel, partial.toolCalls.length, partial.turnCount);
				onUpdate?.({
					content: [{ type: "text", text: "" }],
					details: { ...partial, toolCalls: [...partial.toolCalls] } as unknown as AgentDetails,
				});
			};

			const onEvent = (event: AgentStreamEvent) => {
				switch (event.kind) {
					case "tool_start":
						partial.toolCalls.push(event.toolCall);
						break;
					case "task_progress":
						partial.taskProgress = event.taskProgress;
						break;
					case "message":
						if (event.text) partial.latestMessage = event.text;
						if (event.model) partial.model = event.model;
						break;
					case "turn_end":
						partial.turnCount++;
						break;
				}
				emitUpdate();
			};

			// Initial status
			setStatusRunning(ctx, agentId, agentLabel, 0, 0);

			try {
				let result = await spawnAgent(
					agentConfig,
					params.task,
					{ name, model, cwd: ctx.cwd, env, sessionDir, extensionTools, onEvent },
					signal,
				);

				// Retry with default model if the requested model wasn't found
				if (result.exitCode === 1 && model && result.error?.includes("not found") && result.usage.turns === 0) {
					if (ctx.hasUI) {
						ctx.ui.notify(`Model "${model}" not found — retrying with default model`, "warning");
					}
					const retrySessionDir = `${sessionDir}-retry`;
					fs.mkdirSync(retrySessionDir, { recursive: true });
					partial.toolCalls = [];
					partial.turnCount = 0;
					partial.taskProgress = undefined;
					partial.latestMessage = undefined;
					result = await spawnAgent(
						agentConfig,
						params.task,
						{ name, model: undefined, cwd: ctx.cwd, env, sessionDir: retrySessionDir, extensionTools, onEvent },
						signal,
					);
				}

				const ok = result.exitCode === 0;

				// Clear footer status — result is now in the main panel
				clearStatus(ctx, agentId);

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
					taskProgress: result.taskProgress,
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

				const textContent = result.output ? `${header}\n\n${result.output}` : `${header}\n\n(no output)`;

				return {
					content: [{ type: "text", text: textContent }],
					details,
				};
			} catch (error) {
				clearStatus(ctx, agentId);
				const msg = error instanceof Error ? error.message : String(error);
				return { content: [{ type: "text", text: msg }], isError: true, details: null as unknown as AgentDetails };
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
			text += `\n  ${theme.fg("dim", preview)}`;
			return new Text(text, 0, 0);
		},

		// ------------------------------------------------------------------
		// renderResult — rich display of the subagent's activity and output
		// ------------------------------------------------------------------

		renderResult(result, { expanded, isPartial }, theme, _context) {
			const details = result.details as (AgentDetails & Partial<AgentPartialDetails>) | undefined;

			if (!details) {
				const text = result.content[0];
				return new Text(text?.type === "text" ? text.text : "(no output)", 0, 0);
			}

			const fg = theme.fg.bind(theme);

			// --- In-progress view (streaming) ---
			if (isPartial) {
				return renderPartialView(details as AgentPartialDetails, fg, theme);
			}

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

				if (details.taskProgress) {
					const taskLines = renderCompactTaskProgressLines(details.taskProgress, { fg });
					if (taskLines.length > 0) {
						container.addChild(new Spacer(1));
						container.addChild(new Text(fg("muted", "─── Progress ───"), 0, 0));
						container.addChild(new Text(taskLines.join("\n"), 0, 0));
					}
				}

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

			// --- Collapsed view (completed) ---
			const modelLabel = details.model ? fg("muted", ` (${details.model})`) : "";
			const stats = fg("dim", ` — ${details.toolCalls.length} tools, ${formatDuration(details.durationMs)}`);
			let text = `${icon} ${fg("toolTitle", theme.bold(details.agent))}${modelLabel}${stats}`;

			if (isError && details.error) {
				text += `\n${fg("error", `Error: ${details.error}`)}`;
			}

			const taskSummary = details.taskProgress ? formatTaskProgressSummary(details.taskProgress) : null;
			if (taskSummary) {
				text += `\n${fg("dim", `Tasks: ${taskSummary}`)}`;
			}

			if (details.output) {
				const preview = details.output.split("\n").slice(0, 3).join("\n");
				text += `\n${fg("toolOutput", preview)}`;
				if (details.output.split("\n").length > 3) {
					text += `\n${fg("muted", "...")}`;
				}
			} else if (!isError) {
				text += `\n${fg("muted", "(no output)")}`;
			}

			text += `\n${fg("muted", "(Ctrl+O to expand)")}`;
			return new Text(text, 0, 0);
		},
	});
}
