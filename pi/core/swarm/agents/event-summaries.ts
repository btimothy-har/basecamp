/** Pure event → display-text extraction for the daemon reporter. */

const DISPLAY_TEXT_LIMIT = 240;

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

export function displayText(value: unknown, limit = DISPLAY_TEXT_LIMIT): string | null {
	if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") return null;
	const text = collapseWhitespace(String(value));
	if (!text) return null;
	return truncateText(text, limit);
}

export function messageText(value: string): string | null {
	const text = value.trim();
	return text ? text : null;
}

export function safeString(value: unknown): string | null {
	return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
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

export function extractToolName(event: unknown): string | null {
	const payload = asRecord(event);
	if (!payload) return null;
	return safeString(payload.toolName) ?? safeString(payload.tool_name) ?? safeString(payload.name);
}

export function extractToolInput(event: unknown): unknown {
	const payload = asRecord(event);
	if (!payload) return null;
	return payload.args ?? payload.input ?? payload.parameters ?? payload.toolInput ?? null;
}

export function extractSkillName(toolName: string | null, input: unknown): string | null {
	if (toolName !== "skill") return null;
	const args = asRecord(input);
	return safeString(args?.name);
}

function summarizeNamedValue(name: string, value: unknown): string | null {
	const text = displayText(value);
	return text ? `${name} ${text}` : null;
}

export function summarizeToolInput(toolName: string | null, input: unknown): string | null {
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

export function summarizeToolResult(event: unknown, isError: boolean | null): string {
	const payload = asRecord(event);
	const result = payload?.result ?? payload?.partialResult ?? payload?.output ?? payload?.details ?? payload;
	const snippet = displayText(extractResultText(result));
	if (snippet) return isError ? `error: ${snippet}` : snippet;
	return isError ? "error" : "completed";
}

export function eventHasThinking(value: unknown): boolean {
	if (!value || typeof value !== "object") return false;
	if (Array.isArray(value)) return value.some(eventHasThinking);
	const payload = value as Record<string, unknown>;
	const type = safeString(payload.type)?.toLowerCase();
	if (type?.includes("thinking") || type?.includes("reasoning")) return true;
	if ("thinking" in payload || "thinking_delta" in payload || "thinkingDelta" in payload) return true;
	return eventHasThinking(payload.delta) || eventHasThinking(payload.content) || eventHasThinking(payload.message);
}

export function extractMessageRole(event: unknown): string | null {
	const payload = asRecord(event);
	const message = asRecord(payload?.message);
	return safeString(message?.role) ?? safeString(payload?.role);
}

export function extractVisibleTextFromMessageEvent(event: unknown): string {
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

export function appendText(current: string, addition: string): string {
	return addition ? `${current}${addition}` : current;
}
