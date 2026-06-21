import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { DaemonConnection } from "./client.ts";
import { PROTOCOL_VERSION } from "./frames.ts";

const FLUSH_DELAY_MS = 50;
const DISPLAY_TEXT_LIMIT = 240;
const ASSISTANT_BUFFER_LIMIT = 2_000;

const TOOL_SUMMARY_KEYS = ["path", "file", "target", "command", "query", "pattern", "name", "agent"] as const;

type AgentMessageContentPart = {
	type?: string;
	text?: unknown;
	thinking?: unknown;
};

type AgentMessage = {
	role?: string;
	content?: unknown;
};

function collapseWhitespace(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

function truncateText(value: string, limit = DISPLAY_TEXT_LIMIT): string {
	if (value.length <= limit) return value;
	return `${value.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function displayText(value: unknown, limit = DISPLAY_TEXT_LIMIT): string | null {
	if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return null;
	const text = collapseWhitespace(String(value));
	if (!text) return null;
	return truncateText(text, limit);
}

function safeString(value: unknown): string | null {
	return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function extractTextFromContent(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((part): part is AgentMessageContentPart => Boolean(part) && typeof part === "object")
		.filter((part) => part.type === "text" && typeof part.text === "string")
		.map((part) => part.text as string)
		.join("\n");
}

export function extractLastAssistantMessage(messages: unknown): string {
	if (!Array.isArray(messages)) return "";
	let last = "";
	for (const message of messages) {
		if (!message || typeof message !== "object") continue;
		const candidate = message as AgentMessage;
		if (candidate.role !== "assistant") continue;
		const text = extractTextFromContent(candidate.content);
		if (text) last = text;
	}
	return last;
}

function extractToolName(event: unknown): string | null {
	const payload = asRecord(event);
	if (!payload) return null;
	return safeString(payload.toolName) ?? safeString(payload.tool_name) ?? safeString(payload.name);
}

function extractToolInput(event: unknown): unknown {
	const payload = asRecord(event);
	if (!payload) return null;
	return payload.args ?? payload.input ?? payload.parameters ?? payload.toolInput ?? null;
}

function summarizeNamedValue(name: string, value: unknown): string | null {
	const text = displayText(value);
	return text ? `${name} ${text}` : null;
}

function summarizeToolInput(toolName: string | null, input: unknown): string | null {
	const args = asRecord(input);
	if (!args) return null;

	if (toolName === "read") return summarizeNamedValue("read", args.path ?? args.file);
	if (toolName === "bash") return summarizeNamedValue("bash", args.command);
	if (toolName === "edit") return summarizeNamedValue("edit", args.path ?? args.file);
	if (toolName === "write") return summarizeNamedValue("write", args.path ?? args.file);
	if (toolName === "ls") return summarizeNamedValue("ls", args.path ?? args.cwd);
	if (toolName === "grep" || toolName === "rg") return summarizeNamedValue(toolName, args.pattern ?? args.query);
	if (toolName === "dispatch_agent") {
		const agent = displayText(args.agent);
		const name = displayText(args.name);
		const parts = ["dispatch", agent, name].filter(Boolean);
		return parts.length > 1 ? parts.join(" ") : "dispatch agent";
	}

	for (const key of TOOL_SUMMARY_KEYS) {
		const text = displayText(args[key]);
		if (text) return toolName ? `${toolName} ${text}` : text;
	}
	return toolName ? `${toolName} called` : null;
}

function extractResultText(result: unknown): string {
	if (typeof result === "string") return result;
	const payload = asRecord(result);
	if (!payload) return "";
	const contentText = extractTextFromContent(payload.content);
	if (contentText) return contentText;
	for (const key of ["text", "message", "error", "stdout", "stderr", "result", "preview"] as const) {
		const value = payload[key];
		if (typeof value === "string") return value;
	}
	return "";
}

function summarizeToolResult(event: unknown, isError: boolean | null): string {
	const payload = asRecord(event);
	const result = payload?.result ?? payload?.partialResult ?? payload?.output ?? payload?.details ?? payload;
	const snippet = displayText(extractResultText(result));
	if (snippet) return isError ? `error: ${snippet}` : snippet;
	return isError ? "error" : "completed";
}

function eventHasThinking(value: unknown): boolean {
	if (!value || typeof value !== "object") return false;
	if (Array.isArray(value)) return value.some(eventHasThinking);
	const payload = value as Record<string, unknown>;
	const type = safeString(payload.type)?.toLowerCase();
	if (type?.includes("thinking") || type?.includes("reasoning")) return true;
	if ("thinking" in payload || "thinking_delta" in payload || "thinkingDelta" in payload) return true;
	return eventHasThinking(payload.delta) || eventHasThinking(payload.content) || eventHasThinking(payload.message);
}

function extractMessageRole(event: unknown): string | null {
	const payload = asRecord(event);
	const message = asRecord(payload?.message);
	return safeString(message?.role) ?? safeString(payload?.role);
}

function extractVisibleTextFromMessageEvent(event: unknown): string {
	const payload = asRecord(event);
	if (!payload) return "";
	const type = safeString(payload.type)?.toLowerCase();
	if (type?.includes("thinking") || type?.includes("reasoning")) return "";

	for (const key of ["text_delta", "textDelta"] as const) {
		const text = typeof payload[key] === "string" ? payload[key] : null;
		if (text) return text;
	}

	const delta = asRecord(payload.delta);
	if (delta) {
		const deltaType = safeString(delta.type)?.toLowerCase();
		if (deltaType?.includes("thinking") || deltaType?.includes("reasoning")) return "";
		if (!deltaType || deltaType === "text" || deltaType === "text_delta") {
			const deltaText = extractTextFromContent(delta.content) || (typeof delta.text === "string" ? delta.text : "");
			if (deltaText) return deltaText;
		}
	}

	const message = asRecord(payload.message);
	if (message) return extractTextFromContent(message.content);

	const contentText = extractTextFromContent(payload.content);
	if (contentText) return contentText;

	return typeof payload.text === "string" ? payload.text : "";
}

function appendBounded(current: string, addition: string): string {
	if (!addition) return current;
	const next = `${current}${addition}`;
	if (next.length <= ASSISTANT_BUFFER_LIMIT) return next;
	return next.slice(next.length - ASSISTANT_BUFFER_LIMIT);
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export function registerDaemonReporter(
	pi: ExtensionAPI,
	options: {
		connectionPromise: Promise<DaemonConnection>;
		runId: string;
		agentId: string;
	},
): void {
	const { connectionPromise, runId, agentId } = options;
	const reportToken = process.env.BASECAMP_REPORT_TOKEN;
	if (!reportToken) return;

	let assistantBuffer = "";
	let thinkingReported = false;
	let activeMessageRole: string | null = null;

	const sendTelemetry = async (kind: string, payload: Record<string, unknown>): Promise<void> => {
		try {
			const connection = await connectionPromise;
			connection.send({
				type: "telemetry",
				v: PROTOCOL_VERSION,
				run_id: runId,
				agent_id: agentId,
				report_token: reportToken,
				kind,
				payload,
			});
		} catch {
			// never throw from telemetry hooks
		}
	};

	const sendDisplayTelemetry = (kind: string, payload: Record<string, unknown>): void => {
		void sendTelemetry(kind, payload);
	};

	const sendThinkingMarker = (): void => {
		if (thinkingReported) return;
		thinkingReported = true;
		sendDisplayTelemetry("thinking", {
			category: "assistant",
			label: "thinking",
			snippet: "thinking…",
		});
	};

	const flushAssistantOutput = (): void => {
		const snippet = displayText(assistantBuffer);
		assistantBuffer = "";
		if (!snippet) return;
		sendDisplayTelemetry("assistant_output", {
			category: "assistant",
			label: "assistant",
			snippet,
		});
	};

	pi.on("tool_execution_start", (event) => {
		const toolName = extractToolName(event);
		void sendTelemetry("tool_execution_start", {
			toolCallId: safeString(asRecord(event)?.toolCallId) ?? null,
			toolName,
		});

		const snippet = summarizeToolInput(toolName, extractToolInput(event));
		sendDisplayTelemetry("tool_call", {
			category: "tool",
			label: toolName ?? "tool",
			snippet: snippet ?? (toolName ? `${toolName} called` : "tool called"),
			toolName,
		});
	});

	pi.on("tool_execution_end", (event) => {
		const payload = asRecord(event);
		const toolName = extractToolName(event);
		const isError = typeof payload?.isError === "boolean" ? payload.isError : null;
		void sendTelemetry("tool_execution_end", {
			toolCallId: safeString(payload?.toolCallId) ?? null,
			toolName,
			isError,
		});
		sendDisplayTelemetry("tool_result", {
			category: "tool",
			label: toolName ?? "tool",
			snippet: summarizeToolResult(event, isError),
			toolName,
			isError,
		});
	});

	pi.on("message_start", (event) => {
		assistantBuffer = "";
		thinkingReported = false;
		activeMessageRole = extractMessageRole(event);
	});

	pi.on("message_update", (event) => {
		if (activeMessageRole && activeMessageRole !== "assistant") return;
		if (eventHasThinking(event)) sendThinkingMarker();
		assistantBuffer = appendBounded(assistantBuffer, extractVisibleTextFromMessageEvent(event));
	});

	pi.on("message_end", (event) => {
		const role = extractMessageRole(event) ?? activeMessageRole;
		if (role && role !== "assistant") {
			activeMessageRole = null;
			return;
		}
		if (eventHasThinking(event)) sendThinkingMarker();
		const fullText = extractVisibleTextFromMessageEvent(event);
		if (fullText) assistantBuffer = appendBounded("", fullText);
		flushAssistantOutput();
		activeMessageRole = null;
	});

	pi.on("turn_end", (event) => {
		flushAssistantOutput();
		const payload = event as { turnIndex?: unknown; toolResults?: unknown };
		void sendTelemetry("turn_end", {
			turnIndex: typeof payload.turnIndex === "number" ? payload.turnIndex : null,
			toolCount: Array.isArray(payload.toolResults) ? payload.toolResults.length : null,
		});
	});

	pi.on("agent_end", async (event) => {
		try {
			const payload = event as { messages?: unknown };
			const result = extractLastAssistantMessage(payload.messages);
			const resultSnippet = displayText(result);
			if (resultSnippet) {
				await sendTelemetry("agent_result", {
					category: "result",
					label: "result",
					snippet: resultSnippet,
				});
			}
			const connection = await connectionPromise;
			connection.send({
				type: "result_report",
				v: PROTOCOL_VERSION,
				run_id: runId,
				agent_id: agentId,
				report_token: reportToken,
				status: "ok",
				result,
				error: null,
				usage: null,
			});
			await sleep(FLUSH_DELAY_MS);
		} catch {
			// never throw from agent_end hook
		}
	});
}
