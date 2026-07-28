/**
 * Continuation guard — reading the transcript.
 *
 * Messages arrive as `AgentMessage`, a union the SDK does not export cleanly
 * (it includes custom messages absent from `Message`), so these read a local
 * structural shape — the same approach as `#core/swarm/agents/event-summaries.ts`.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

type TranscriptContentPart = {
	type?: string;
	text?: unknown;
};

type TranscriptMessage = {
	role?: string;
	content?: unknown;
	stopReason?: unknown;
};

function asMessage(value: unknown): TranscriptMessage | null {
	return value && typeof value === "object" ? (value as TranscriptMessage) : null;
}

/** Text parts are fragments of one message, so they concatenate rather than being joined by newlines. */
export function textFromContent(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((part): part is TranscriptContentPart => Boolean(part) && typeof part === "object")
		.filter((part) => part.type === "text" && typeof part.text === "string")
		.map((part) => part.text as string)
		.join("");
}

/** The last assistant message carrying text — the stop the rubric judges. */
export function finalAssistantText(messages: unknown): string {
	if (!Array.isArray(messages)) return "";
	for (let index = messages.length - 1; index >= 0; index--) {
		const message = asMessage(messages[index]);
		if (message?.role !== "assistant") continue;
		const text = textFromContent(message.content).trim();
		if (text !== "") return text;
	}
	return "";
}

/**
 * Whether the model call itself failed. Mirrors how Pi decides `willRetry`
 * (which it never hands to extensions): inspect the most recent assistant
 * message and stop, so a failure now is not masked by an earlier good turn.
 */
export function providerErrored(messages: unknown): boolean {
	if (!Array.isArray(messages)) return false;
	for (let index = messages.length - 1; index >= 0; index--) {
		const message = asMessage(messages[index]);
		if (message?.role !== "assistant") continue;
		return message.stopReason === "error" || message.stopReason === "aborted";
	}
	return false;
}

export function recentUserMessages(sessionManager: ExtensionContext["sessionManager"], limit = 5): string[] {
	const messages: string[] = [];
	for (const entry of sessionManager.getEntries()) {
		if (entry.type === "message" && entry.message.role === "user") {
			messages.push(textFromContent(entry.message.content));
		}
	}
	return messages.slice(-limit);
}
