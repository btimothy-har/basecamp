import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type {
	AssistantMessage,
	Message,
	TextContent,
	ToolCall,
	ToolResultMessage,
	UserMessage,
} from "@earendil-works/pi-ai";
import {
	buildSessionContext,
	convertToLlm,
	type SessionEntry,
	serializeConversation,
} from "@earendil-works/pi-coding-agent";

function isVisibleAgentMessage(message: AgentMessage): boolean {
	if (message.role !== "custom") return true;
	return message.display;
}

function textOnlyContent(content: UserMessage["content"]): UserMessage["content"] {
	if (typeof content === "string") return content;
	return content.filter((part): part is TextContent => part.type === "text");
}

const TOOL_CALL_ARGUMENT_MAX_CHARS = 1_500;

function boundedToolCall(part: ToolCall): ToolCall {
	const serialized = JSON.stringify(part.arguments);
	if (serialized.length <= TOOL_CALL_ARGUMENT_MAX_CHARS) return part;
	const omitted = serialized.length - TOOL_CALL_ARGUMENT_MAX_CHARS;
	return {
		...part,
		arguments: {
			truncated_arguments: `${serialized.slice(0, TOOL_CALL_ARGUMENT_MAX_CHARS)}\n[... ${omitted} more characters truncated]`,
		},
	};
}

function visibleMessage(message: Message): Message {
	if (message.role === "user") {
		return { ...message, content: textOnlyContent(message.content) } satisfies UserMessage;
	}
	if (message.role === "assistant") {
		return {
			...message,
			content: message.content.flatMap((part) => {
				if (part.type === "thinking") return [];
				return [part.type === "toolCall" ? boundedToolCall(part) : part];
			}),
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
