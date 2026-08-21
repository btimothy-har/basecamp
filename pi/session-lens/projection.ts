import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AssistantMessage, Message, TextContent, ToolResultMessage, UserMessage } from "@earendil-works/pi-ai";
import {
	buildSessionContext,
	convertToLlm,
	serializeConversation,
	type SessionEntry,
} from "@earendil-works/pi-coding-agent";

function isVisibleAgentMessage(message: AgentMessage): boolean {
	if (message.role !== "custom") return true;
	return message.display;
}

function textOnlyContent(content: UserMessage["content"]): UserMessage["content"] {
	if (typeof content === "string") return content;
	return content.filter((part): part is TextContent => part.type === "text");
}

function visibleMessage(message: Message): Message {
	if (message.role === "user") {
		return { ...message, content: textOnlyContent(message.content) } satisfies UserMessage;
	}
	if (message.role === "assistant") {
		return {
			...message,
			content: message.content.filter((part) => part.type !== "thinking"),
		} satisfies AssistantMessage;
	}
	return {
		...message,
		content: message.content.filter((part): part is TextContent => part.type === "text"),
	} satisfies ToolResultMessage;
}

export function projectVisibleSession(entries: SessionEntry[], leafId?: string | null): string {
	const session = buildSessionContext(entries, leafId);
	const visibleAgentMessages = session.messages.filter(isVisibleAgentMessage);
	const visibleLlmMessages = convertToLlm(visibleAgentMessages).map(visibleMessage);
	return serializeConversation(visibleLlmMessages).trim();
}
