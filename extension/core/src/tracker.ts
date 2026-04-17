/**
 * Tracker — persistent context & progress widgets updated by background LLM extraction.
 *
 * Two widgets rendered above the editor:
 *   - Context: title, goal, assumptions (replaced on agent_start)
 *   - Progress: cumulative list of work done (appended on agent_end)
 *
 * Extraction runs async via `pi -p` with a fast model. Never blocks the main agent.
 * State is persisted via appendEntry for session resume.
 */

import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
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
import { resolveModelAlias } from "../../config.ts";

const execFileAsync = promisify(execFileCb);

// ============================================================================
// Types
// ============================================================================

interface ContextState {
	title: string;
	goal: string;
	assumptions: string[];
}

interface ProgressState {
	items: string[];
}

interface TrackerPersistedState {
	context: ContextState | null;
	progress: ProgressState;
}

// ============================================================================
// Serialization
// ============================================================================

/** Serialize session branch into a compact text representation for the extraction prompt. */
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
			// Keep tool results brief — they're context, not the focus
			const preview = text.length > 200 ? `${text.slice(0, 200)}...` : text;
			if (preview.trim()) lines.push(`[Tool:${result.toolName}]\n${preview.trim()}`);
		}
	}

	return lines.join("\n\n");
}

// ============================================================================
// Extraction
// ============================================================================

const CONTEXT_PROMPT = `You are extracting structured context from a coding session conversation.

Given the conversation below, extract the current working context. Return ONLY valid JSON, no markdown fences, no explanation.

Schema:
{"title": "short task title (3-6 words)", "goal": "what success looks like (1 sentence)", "assumptions": ["assumption 1", "assumption 2"]}

Rules:
- Title should describe the current task, not the project
- Goal should be concrete and verifiable
- Assumptions are things the agent is taking as given that could be wrong
- If the conversation is just starting or unclear, use your best judgment
- 2-4 assumptions max

Conversation:
`;

const PROGRESS_PROMPT = `You are extracting a progress summary from a coding session conversation.

Given the conversation and existing progress items below, return an UPDATED cumulative list of what has been accomplished. Return ONLY a valid JSON array of strings, no markdown fences, no explanation.

Rules:
- Each item should be a concise past-tense statement (e.g. "Added JWT validation middleware")
- Merge/deduplicate with existing items — don't repeat work already listed
- Keep items specific and actionable, not vague
- Order chronologically
- 10 items max — if exceeding, consolidate older items

Existing progress:
`;

async function extractContext(conversation: string, cwd: string, fallbackModel?: string): Promise<ContextState | null> {
	try {
		const model = resolveModelAlias("fast", fallbackModel);
		const prompt = CONTEXT_PROMPT + conversation;
		const { stdout } = await execFileAsync("pi", [
			"-p", "--no-session", "--no-extensions", "--no-skills",
			"--no-prompt-templates", "--no-themes",
			"--model", model, prompt,
		], {
			cwd,
			timeout: 30_000,
			env: { ...process.env },
		});

		const cleaned = stdout.trim().replace(/^```json?\n?|\n?```$/g, "");
		const parsed = JSON.parse(cleaned);
		if (parsed.title && parsed.goal && Array.isArray(parsed.assumptions)) {
			return parsed as ContextState;
		}
		return null;
	} catch {
		return null;
	}
}

async function extractProgress(
	conversation: string,
	existing: string[],
	cwd: string,
	fallbackModel?: string,
): Promise<string[] | null> {
	try {
		const model = resolveModelAlias("fast", fallbackModel);
		const prompt = PROGRESS_PROMPT + JSON.stringify(existing) + "\n\nConversation:\n" + conversation;
		const { stdout } = await execFileAsync("pi", [
			"-p", "--no-session", "--no-extensions", "--no-skills",
			"--no-prompt-templates", "--no-themes",
			"--model", model, prompt,
		], {
			cwd,
			timeout: 30_000,
			env: { ...process.env },
		});

		const cleaned = stdout.trim().replace(/^```json?\n?|\n?```$/g, "");
		const parsed = JSON.parse(cleaned);
		if (Array.isArray(parsed) && parsed.every((item: unknown) => typeof item === "string")) {
			return parsed as string[];
		}
		return null;
	} catch {
		return null;
	}
}

// ============================================================================
// Widget Rendering
// ============================================================================

function renderWidget(
	context: ContextState | null,
	progress: ProgressState,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	bold: Theme["bold"],
	width: number,
): string[] {
	const lines: string[] = [];
	const separator = fg("dim", "─".repeat(Math.min(width, 48)));

	if (context) {
		lines.push(fg("accent", bold("Context")));
		lines.push(`  ${fg("dim", "Title")}  ${context.title}`);
		lines.push(`  ${fg("dim", "Goal")}   ${context.goal}`);
		if (context.assumptions.length > 0) {
			lines.push(`  ${fg("dim", "Assumptions")}`);
			for (const a of context.assumptions) {
				lines.push(`  ${fg("muted", "•")} ${a}`);
			}
		}
	}

	if (progress.items.length > 0) {
		if (context) lines.push(separator);
		lines.push(fg("accent", bold("Progress")));
		for (const item of progress.items) {
			lines.push(`  ${fg("success", "✓")} ${fg("muted", item)}`);
		}
	}

	return lines;
}

// ============================================================================
// Registration
// ============================================================================

export function registerTracker(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;
	let contextState: ContextState | null = null;
	let progressState: ProgressState = { items: [] };
	let pendingExtraction: AbortController | null = null;

	function cancelPending(): void {
		if (pendingExtraction) {
			pendingExtraction.abort();
			pendingExtraction = null;
		}
	}

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		const lines = renderWidget(
			contextState,
			progressState,
			ctx.ui.theme.fg.bind(ctx.ui.theme),
			ctx.ui.theme.bold.bind(ctx.ui.theme),
			48,
		);

		if (lines.length > 0) {
			ctx.ui.setWidget("basecamp-tracker", lines);
		} else {
			ctx.ui.setWidget("basecamp-tracker", undefined);
		}
	}

	function persistState(): void {
		pi.appendEntry("tracker-state", {
			context: contextState,
			progress: progressState,
		} satisfies TrackerPersistedState);
	}

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		contextState = null;
		progressState = { items: [] };

		// Restore from persisted entries
		const entries = sessionCtx.sessionManager.getEntries();
		const trackerEntry = entries
			.filter((e) => e.type === "custom" && (e as { customType?: string }).customType === "tracker-state")
			.pop() as { data?: TrackerPersistedState } | undefined;

		if (trackerEntry?.data) {
			contextState = trackerEntry.data.context ?? null;
			progressState = trackerEntry.data.progress ?? { items: [] };
		}

		updateWidget();
	});

	// --- Extract context on agent_start ---
	pi.on("agent_start", async (_event, agentCtx) => {
		if (!agentCtx.hasUI) return;

		cancelPending();
		const controller = new AbortController();
		pendingExtraction = controller;

		const branch = agentCtx.sessionManager.getBranch();
		const conversation = serializeBranch(branch);
		if (!conversation.trim()) return;

		// Fire and forget — don't block the agent
		extractContext(conversation, agentCtx.cwd, agentCtx.model?.id).then((result) => {
			if (controller.signal.aborted) return;
			if (result) {
				contextState = result;
				updateWidget();
				persistState();
			}
			pendingExtraction = null;
		});
	});

	// --- Extract progress on agent_end ---
	pi.on("agent_end", async (_event, agentCtx) => {
		if (!agentCtx.hasUI) return;

		cancelPending();
		const controller = new AbortController();
		pendingExtraction = controller;

		const branch = agentCtx.sessionManager.getBranch();
		const conversation = serializeBranch(branch);
		if (!conversation.trim()) return;

		// Fire and forget
		extractProgress(conversation, progressState.items, agentCtx.cwd, agentCtx.model?.id).then((result) => {
			if (controller.signal.aborted) return;
			if (result) {
				progressState = { items: result };
				updateWidget();
				persistState();
			}
			pendingExtraction = null;
		});
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		cancelPending();
		ctx = null;
	});
}
