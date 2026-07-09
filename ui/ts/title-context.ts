/** Title context assembly — compacts the user's own messages into a bounded prompt context. */

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { TextContent, UserMessage } from "@earendil-works/pi-ai";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";

const FIRST_USER_MESSAGES = 3;
const RECENT_USER_MESSAGES = 3;
const MAX_CONTEXT_CHARS = 8_000;
const MAX_ENTRY_CHARS = 1_200;
const MAX_TEXT_CHARS = 900;
const MAX_LATEST_PROMPT_CHARS = 1_200;
const MAX_LINE_CHARS = 240;
const MAX_TEXT_LINES = 80;

function truncate(value: string, maxChars: number): string {
	return value.length > maxChars ? `${value.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…` : value;
}

function compactText(raw: string, maxChars: number): string {
	const withoutFences = raw.replace(/```[\s\S]*?```/g, "[fenced code block omitted]");
	const lines = withoutFences.replace(/\r\n?/g, "\n").split("\n");
	const compacted: string[] = [];
	let omittedLogLines = 0;

	function flushOmittedLogs(): void {
		if (omittedLogLines === 0) return;
		compacted.push(`[${omittedLogLines} log-like line${omittedLogLines === 1 ? "" : "s"} omitted]`);
		omittedLogLines = 0;
	}

	for (const line of lines) {
		const trimmed = line.trim();
		const isLogLike =
			/^(?:\[[^\]]*(?:DEBUG|INFO|WARN|ERROR|TRACE)[^\]]*\]|(?:DEBUG|INFO|WARN|ERROR|TRACE)\b|\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})/.test(
				trimmed,
			);
		if (isLogLike) {
			omittedLogLines += 1;
			continue;
		}

		flushOmittedLogs();
		compacted.push(truncate(line.trimEnd(), MAX_LINE_CHARS));
		if (compacted.length >= MAX_TEXT_LINES) {
			compacted.push("[additional lines omitted]");
			break;
		}
	}

	flushOmittedLogs();
	return truncate(compacted.join("\n").trim(), maxChars);
}

function userText(message: UserMessage): string {
	return typeof message.content === "string"
		? message.content
		: message.content
				.filter((content): content is TextContent => content.type === "text")
				.map((content) => content.text)
				.join("\n");
}

function appendBounded(parts: string[], part: string, maxChars: number): boolean {
	const separator = parts.length === 0 ? "" : "\n\n";
	const currentLength = parts.join("\n\n").length;
	const nextLength = currentLength + separator.length + part.length;
	if (nextLength <= maxChars) {
		parts.push(part);
		return true;
	}

	const remaining = maxChars - currentLength - separator.length;
	if (remaining > 40) parts.push(truncate(part, remaining));
	return false;
}

export function buildTitleContext(entries: SessionEntry[], latestPrompt?: string): string {
	const parts: string[] = [];
	const userMessages = entries
		.filter((entry) => entry.type === "message")
		.filter((entry) => (entry.message as AgentMessage).role === "user");
	const selectedMessages =
		userMessages.length <= FIRST_USER_MESSAGES + RECENT_USER_MESSAGES
			? userMessages
			: [...userMessages.slice(0, FIRST_USER_MESSAGES), ...userMessages.slice(-RECENT_USER_MESSAGES)];
	const selectedParts: string[] = [];

	for (const entry of selectedMessages) {
		const text = compactText(userText(entry.message as UserMessage), MAX_TEXT_CHARS);
		if (text) selectedParts.push(truncate(`[User]\n${text}`, MAX_ENTRY_CHARS));
	}

	let selectedLength = 0;
	for (let index = selectedParts.length - 1; index >= 0; index -= 1) {
		const part = selectedParts[index]!;
		const separatorLength = parts.length === 0 ? 0 : 2;
		const nextLength = selectedLength + separatorLength + part.length;
		if (nextLength <= MAX_CONTEXT_CHARS) {
			parts.unshift(part);
			selectedLength = nextLength;
			continue;
		}

		const remaining = MAX_CONTEXT_CHARS - selectedLength - separatorLength;
		if (remaining > 40) parts.unshift(truncate(part, remaining));
		break;
	}

	const pendingPrompt = latestPrompt ? compactText(latestPrompt, MAX_LATEST_PROMPT_CHARS) : "";
	if (pendingPrompt) appendBounded(parts, `[Pending User Prompt]\n${pendingPrompt}`, MAX_CONTEXT_CHARS);

	return parts.join("\n\n");
}
