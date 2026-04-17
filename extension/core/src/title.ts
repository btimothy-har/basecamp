/**
 * Title — auto-extracted session title displayed above the editor.
 *
 * Right-aligned, compact, dimmed. Extracted in the background via `pi -p`
 * on the first agent turn, or manually via `/title`.
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
import type {
	ExtensionAPI,
	ExtensionContext,
	SessionEntry,
	Theme,
} from "@mariozechner/pi-coding-agent";
import { visibleWidth } from "@mariozechner/pi-tui";
import { resolveModelAlias } from "../../config.ts";

// ============================================================================
// Background Title Extraction
// ============================================================================

const TITLE_SYSTEM_PROMPT = "You are a title generator. Output exactly one short title (4-5 words). No markdown, no quotes, no alternatives, no explanation. Just the title.";

const TITLE_PROMPT = `Give a short title (4-5 words) that captures the overall theme of this entire coding session. Consider the full conversation, not just the latest messages. Return ONLY the title, no quotes, no explanation, no punctuation at the end.

Conversation:
`;

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
		const firstLine = stdout.trim().split("\n")[0] ?? "";
		const cleaned = firstLine.replace(/\*\*/g, "").replace(/^["'`]|["'`]$/g, "").replace(/\.+$/, "").trim();
		const words = cleaned.split(/\s+/);
		const title = words.length > 5 ? words.slice(0, 5).join(" ") : cleaned;
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

function renderTitleWidget(
	title: string,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	bg: (color: Parameters<Theme["bg"]>[0], text: string) => string,
	bold: Theme["bold"],
	width: number,
): string[] {
	const text = fg("mdHeading", bold(title));
	const vw = visibleWidth(text);
	const pad = Math.max(0, width - vw - 1);
	const line = `${" ".repeat(pad)}${text} `;
	const linePad = Math.max(0, width - visibleWidth(line));
	return [bg("selectedBg", line + " ".repeat(linePad))];
}

// ============================================================================
// Registration
// ============================================================================

/** Last 4 hex chars of UUIDv7 — random portion, safe for disambiguation. */
function shortSessionId(sessionId: string): string {
	return sessionId.replace(/-/g, "").slice(-4);
}

function formatTitle(title: string, tag: string): string {
	return `${title} [${tag}]`;
}

export function registerTitle(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;
	let title: string | null = null;
	let sessionTag: string | null = null;
	let pendingTitle: AbortController | null = null;

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		if (!title) {
			ctx.ui.setWidget("basecamp-title", undefined, { placement: "aboveEditor" });
			return;
		}

		ctx.ui.setWidget("basecamp-title", (_tui, theme) => {
			const fg = theme.fg.bind(theme);
			const bg = theme.bg.bind(theme);
			const bold = theme.bold.bind(theme);
			let cachedLines: string[] | null = null;
			let cachedWidth = 0;

			return {
				invalidate() { cachedLines = null; },
				render(width: number): string[] {
					if (cachedLines && cachedWidth === width) return cachedLines;
					cachedWidth = width;
						const display = displayTitle();
					cachedLines = display ? renderTitleWidget(display, fg, bg, bold, width) : [];
					return cachedLines;
				},
			};
		}, { placement: "aboveEditor" });
	}

	/** Display title with session tag suffix. */
	function displayTitle(): string | null {
		if (!title) return null;
		return sessionTag ? formatTitle(title, sessionTag) : title;
	}

	function persistState(): void {
		pi.appendEntry("title-state", { title });
	}

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
			const extracted = await extractTitle(conversation, cmdCtx.cwd, cmdCtx.model?.id, onError);
			if (extracted) {
				title = extracted;
				const display = displayTitle();
				pi.setSessionName(display ?? title);
				if (ctx?.hasUI) ctx.ui.setTitle(display ?? title);
				updateWidget();
				persistState();
				cmdCtx.ui.notify(`Title: ${display}`, "info");
			}
		},
	});

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		title = null;
		sessionTag = shortSessionId(sessionCtx.sessionManager.getSessionId());

		const entries = sessionCtx.sessionManager.getEntries();
		const titleEntry = entries
			.filter((e) => e.type === "custom" && (e as { customType?: string }).customType === "title-state")
			.pop() as { data?: { title: string | null } } | undefined;

		if (titleEntry?.data?.title) {
			title = titleEntry.data.title;
			const display = displayTitle();
			if (sessionCtx.hasUI) sessionCtx.ui.setTitle(display ?? title);
		}

		updateWidget();
	});

	// --- Background extraction on first agent turn ---
	pi.on("before_agent_start", async (event, agentCtx) => {
		if (title || !agentCtx.hasUI) return;

		pendingTitle?.abort();
		const controller = new AbortController();
		pendingTitle = controller;

		const branch = agentCtx.sessionManager.getBranch();
		let conversation = serializeBranch(branch);
		if (event.prompt) {
			conversation += `\n\n[User]\n${event.prompt}`;
		}
		if (!conversation.trim()) return;

		extractTitle(conversation, agentCtx.cwd, agentCtx.model?.id).then((extracted) => {
			if (controller.signal.aborted) return;
			if (extracted) {
				title = extracted;
				const display = displayTitle();
				pi.setSessionName(display ?? title);
				if (ctx?.hasUI) ctx.ui.setTitle(display ?? title);
				updateWidget();
				persistState();
			}
			pendingTitle = null;
		}).catch(() => {
			pendingTitle = null;
		});
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		pendingTitle?.abort();
		pendingTitle = null;
		ctx = null;
	});
}
