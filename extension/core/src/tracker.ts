/**
 * Tracker — persistent context widget above the editor.
 *
 * Three fields:
 *   - Title: extracted by background pi -p (plaintext, low stakes)
 *   - Goal: set by main agent via update_context tool
 *   - Assumptions: set by main agent via update_context tool
 *
 * State is persisted via appendEntry for session resume.
 */

import { spawn } from "node:child_process";
import type { AgentMessage } from "@mariozechner/pi-agent-core";
import type {
	AssistantMessage,
	TextContent,
	ToolCall,
	ToolResultMessage,
	UserMessage,
} from "@mariozechner/pi-ai";
import { Type } from "@sinclair/typebox";
import type {
	ExtensionAPI,
	ExtensionContext,
	SessionEntry,
	Theme,
} from "@mariozechner/pi-coding-agent";
import { visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";
import { resolveModelAlias } from "../../config.ts";

// ============================================================================
// Types
// ============================================================================

interface TrackerState {
	title: string | null;
	goal: string | null;
	assumptions: string[];
}

// ============================================================================
// Background Title Extraction
// ============================================================================

const TITLE_SYSTEM_PROMPT = "You are a title generator. Output exactly one short title (3-6 words). No markdown, no quotes, no alternatives, no explanation. Just the title.";

/** Run `pi -p` with prompt on stdin, return stdout. */
function piPrint(model: string, systemPrompt: string, prompt: string, cwd: string, timeout: number): Promise<string> {
	return new Promise((resolve, reject) => {
			const proc = spawn("pi", ["-p", "--no-session", "--no-tools", "--model", model, "--system-prompt", systemPrompt], {
			cwd,
			env: { ...process.env },
			stdio: ["pipe", "pipe", "pipe"],
		});

		let stdout = "";
		let stderr = "";
		proc.stdout.on("data", (data: Buffer) => { stdout += data.toString(); });
		proc.stderr.on("data", (data: Buffer) => { stderr += data.toString(); });

		const timer = setTimeout(() => {
			proc.kill();
			reject(new Error("timeout"));
		}, timeout);

		proc.on("close", (code) => {
			clearTimeout(timer);
			if (code === 0) resolve(stdout);
			else reject(new Error(`pi exited ${code}: ${stderr.slice(0, 300)}`));
		});

		proc.stdin.write(prompt);
		proc.stdin.end();
	});
}

const TITLE_PROMPT = `Give a short title (3-6 words) that captures the overall theme of this entire coding session. Consider the full conversation, not just the latest messages. Return ONLY the title, no quotes, no explanation, no punctuation at the end.

Conversation:
`;

/** Serialize session branch into a compact text representation. */
function serializeBranch(entries: SessionEntry[]): string {
	const lines: string[] = [];

	for (const entry of entries) {
		if (entry.type !== "message") continue;
		const msg = entry.message as AgentMessage;

		if (msg.role === "user") {
			const user = msg as UserMessage;
			const text = typeof user.content === "string"
				? user.content
				: user.content.filter((c): c is TextContent => c.type === "text").map((c) => c.text).join("\n");
			if (text.trim()) lines.push(`[User]\n${text.trim()}`);
		} else if (msg.role === "assistant") {
			const assistant = msg as AssistantMessage;
			const textParts = assistant.content
				.filter((c): c is TextContent => c.type === "text")
				.map((c) => c.text);
			const toolCalls = assistant.content
				.filter((c): c is ToolCall => c.type === "toolCall")
				.map((c) => `tool:${c.name}(${JSON.stringify(c.arguments).slice(0, 100)})`);
			const parts = [...textParts, ...toolCalls].filter(Boolean);
			if (parts.length > 0) lines.push(`[Assistant]\n${parts.join("\n")}`);
		} else if (msg.role === "toolResult") {
			const result = msg as ToolResultMessage;
			const text = result.content
				.filter((c): c is TextContent => c.type === "text")
				.map((c) => c.text)
				.join("\n");
			const preview = text.length > 200 ? `${text.slice(0, 200)}...` : text;
			if (preview.trim()) lines.push(`[Tool:${result.toolName}]\n${preview.trim()}`);
		}
	}

	return lines.join("\n\n");
}

async function extractTitle(conversation: string, cwd: string, fallbackModel?: string, onError?: (msg: string) => void): Promise<string | null> {
	try {
		const model = resolveModelAlias("fast", fallbackModel);
		const stdout = await piPrint(model, TITLE_SYSTEM_PROMPT, TITLE_PROMPT + conversation, cwd, 30_000);
		// Take only the first line, strip markdown/quotes/punctuation
		const firstLine = stdout.trim().split("\n")[0] ?? "";
		const title = firstLine.replace(/\*\*/g, "").replace(/^["'`]|["'`]$/g, "").replace(/\.+$/, "").trim();
		if (!title) onError?.("empty response from pi");
		return title || null;
	} catch (err) {
		onError?.(err instanceof Error ? err.message : String(err));
		return null;
	}
}

// ============================================================================
// Widget Rendering
// ============================================================================

function renderWidget(
	state: TrackerState,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	bold: Theme["bold"],
	width: number,
): string[] {
	const hasContent = state.title || state.goal || state.assumptions.length > 0;
	if (!hasContent) return [];

	const inner: string[] = [];
	const boxWidth = Math.min(width, 80);

	if (state.title) {
		inner.push(fg("accent", bold(state.title)));
	}
	if (state.goal) {
		inner.push(`  ${fg("dim", "Goal")}  ${state.goal}`);
	}
	if (state.assumptions.length > 0) {
		inner.push(`  ${fg("dim", "Assumptions")}`);
		for (const a of state.assumptions) {
			inner.push(`  ${fg("muted", "•")} ${a}`);
		}
	}

	// Box-draw border
	const contentWidth = boxWidth - 4;
	const top = fg("dim", `╭${"─".repeat(boxWidth - 2)}╮`);
	const bottom = fg("dim", `╰${"─".repeat(boxWidth - 2)}╯`);
	const lines: string[] = [top];
	for (const line of inner) {
		const wrapped = wrapTextWithAnsi(line, contentWidth);
		for (const wl of wrapped) {
			const vw = visibleWidth(wl);
			const pad = Math.max(0, contentWidth - vw);
			lines.push(`${fg("dim", "│")} ${wl}${" ".repeat(pad)} ${fg("dim", "│")}`);
		}
	}
	lines.push(bottom);
	return lines;
}

// ============================================================================
// Registration
// ============================================================================

export function registerTracker(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;
	let state: TrackerState = { title: null, goal: null, assumptions: [] };
	let pendingTitle: AbortController | null = null;

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		const hasContent = state.title || state.goal || state.assumptions.length > 0;
		if (!hasContent) {
			ctx.ui.setWidget("basecamp-tracker", undefined, { placement: "belowEditor" });
			return;
		}

		ctx.ui.setWidget("basecamp-tracker", (_tui, theme) => {
			const fg = theme.fg.bind(theme);
			const bold = theme.bold.bind(theme);
			let cachedLines: string[] | null = null;
			let cachedWidth = 0;

			return {
				invalidate() { cachedLines = null; },
				render(width: number): string[] {
					if (cachedLines && cachedWidth === width) return cachedLines;
					cachedWidth = width;
					cachedLines = renderWidget(state, fg, bold, width);
					return cachedLines;
				},
			};
		}, { placement: "belowEditor" });
	}

	function persistState(): void {
		pi.appendEntry("tracker-state", state);
	}

	// --- Tool: update_context ---
	pi.registerTool({
		name: "update_context",
		label: "Update Context",
		description: "Update the session context tracker with the current goal and assumptions. Call this when starting a new task, when the goal changes, or when assumptions are established or invalidated.",
		promptSnippet: "Update context tracker (goal + assumptions)",
		parameters: Type.Object({
			goal: Type.String({ description: "What success looks like — concrete and verifiable (1 sentence)" }),
			assumptions: Type.Array(Type.String(), { description: "Things being taken as given that could be wrong (2-4 items)" }),
		}),
		async execute(_id, params, _signal, _onUpdate, _ctx) {
			state.goal = params.goal;
			state.assumptions = params.assumptions;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: "Context updated." }],
				details: { goal: params.goal, assumptions: params.assumptions },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const goal = (args.goal as string) || "...";
			const preview = goal.length > 60 ? `${goal.slice(0, 60)}...` : goal;
			return new Text(
				theme.fg("toolTitle", theme.bold("update_context ")) + theme.fg("dim", preview),
				0, 0,
			);
		},
		renderResult(_result, { isPartial }, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			if (isPartial) return new Text(theme.fg("dim", "..."), 0, 0);
			return new Text(theme.fg("success", "✓") + theme.fg("dim", " context updated"), 0, 0);
		},
	});

	// --- Command: /title ---
	pi.registerCommand("title", {
		description: "Generate a session title from the conversation",
		handler: async (_args, cmdCtx) => {
			const branch = cmdCtx.sessionManager.getBranch();
			const conversation = serializeBranch(branch);
			if (!conversation.trim()) {
				cmdCtx.ui.notify("No conversation to extract title from", "warning");
				return;
			}

			cmdCtx.ui.notify("Extracting title...", "info");
			const onError = (msg: string) => cmdCtx.ui.notify(`Title error: ${msg}`, "error");
			const title = await extractTitle(conversation, cmdCtx.cwd, cmdCtx.model?.id, onError);
			if (title) {
				state.title = title;
				pi.setSessionName(title);
				updateWidget();
				persistState();
				cmdCtx.ui.notify(`Title: ${title}`, "info");
			}
		},
	});

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		state = { title: null, goal: null, assumptions: [] };

		// Restore from persisted entries
		const entries = sessionCtx.sessionManager.getEntries();
		const trackerEntry = entries
			.filter((e) => e.type === "custom" && (e as { customType?: string }).customType === "tracker-state")
			.pop() as { data?: TrackerState } | undefined;

		if (trackerEntry?.data) {
			state = { ...state, ...trackerEntry.data };
		}

		// Restore from tool calls in the branch
		for (const entry of sessionCtx.sessionManager.getBranch()) {
			if (entry.type === "message" && entry.message.role === "toolResult") {
				const msg = entry.message as ToolResultMessage;
				if (msg.toolName === "update_context" && msg.details) {
					const d = msg.details as { goal?: string; assumptions?: string[] };
					if (d.goal) state.goal = d.goal;
					if (d.assumptions) state.assumptions = d.assumptions;
				}
			}
		}

		updateWidget();
	});

	// --- before_agent_start: extract title + inject context reminder ---
	pi.on("before_agent_start", async (event, agentCtx) => {
		// Extract title in background (only if not yet set)
		if (!state.title && agentCtx.hasUI) {
			pendingTitle?.abort();
			const controller = new AbortController();
			pendingTitle = controller;

			const branch = agentCtx.sessionManager.getBranch();
			let conversation = serializeBranch(branch);
			if (event.prompt) {
				conversation += `\n\n[User]\n${event.prompt}`;
			}
			if (conversation.trim()) {
				extractTitle(conversation, agentCtx.cwd, agentCtx.model?.id).then((title) => {
					if (controller.signal.aborted) return;
					if (title) {
						state.title = title;
						pi.setSessionName(title);
						updateWidget();
						persistState();
					}
					pendingTitle = null;
				}).catch(() => {
					pendingTitle = null;
				});
			}
		}

		// Inject context reminder so the agent sees current state
		if (state.goal && agentCtx.hasUI) {
			const lines = [`Current context tracker state:`, `Goal: ${state.goal}`];
			if (state.assumptions.length > 0) {
				lines.push(`Assumptions:\n${state.assumptions.map((a) => `• ${a}`).join("\n")}`);
			}
			lines.push("", "If the goal or assumptions have changed, call `update_context` to update them.");
			pi.sendMessage(
				{
					customType: "tracker-context",
					content: lines.join("\n"),
					display: false,
				},
				{ deliverAs: "steer" },
			);
		}
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		pendingTitle?.abort();
		pendingTitle = null;
		ctx = null;
	});
}
