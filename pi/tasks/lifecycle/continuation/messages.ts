/**
 * Continuation guard — reading the transcript.
 *
 * `agent_end` hands over `AgentMessage`, a union that includes custom messages
 * absent from `Message`, so these read the union directly rather than the
 * narrower provider type.
 */

import type { AgentMessage } from "@earendil-works/pi-agent-core";

/** The rubric needs enough of the stop to judge it, not the whole thing. */
const STOP_TEXT_LIMIT = 4_000;

/** `AgentMessage` also covers bash executions, which carry no content at all. */
type MessageContent = Extract<AgentMessage, { content: unknown }>["content"];
type AssistantMessage = Extract<AgentMessage, { role: "assistant" }>;
type TextPart = { type: "text"; text: string };

/** Text parts are fragments of one message, so they concatenate rather than being joined by newlines. */
export function textFromContent(content: MessageContent): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((part): part is TextPart => part.type === "text" && typeof part.text === "string")
		.map((part) => part.text)
		.join("");
}

function lastAssistantMessage(messages: readonly AgentMessage[]): AssistantMessage | undefined {
	for (let index = messages.length - 1; index >= 0; index--) {
		const message = messages[index];
		if (message?.role === "assistant") return message;
	}
	return undefined;
}

/**
 * The stop the rubric judges: the text of the last assistant message, bounded.
 *
 * Only that message counts. Walking back to an older turn would hand the judge a
 * "let me run the tests next" from several turns ago as though it were the stop,
 * which reads as an unfulfilled intent long after it was fulfilled.
 */
export function finalAssistantText(messages: readonly AgentMessage[]): string {
	const message = lastAssistantMessage(messages);
	if (!message) return "";
	const text = textFromContent(message.content).trim();
	return text.length <= STOP_TEXT_LIMIT ? text : `${text.slice(0, STOP_TEXT_LIMIT)}…`;
}

/**
 * Whether the model call itself failed. Mirrors how Pi decides `willRetry`
 * (which it never hands to extensions): inspect the most recent assistant
 * message and stop, so a failure now is not masked by an earlier good turn.
 */
export function providerErrored(messages: readonly AgentMessage[]): boolean {
	const stopReason = lastAssistantMessage(messages)?.stopReason;
	return stopReason === "error" || stopReason === "aborted";
}
