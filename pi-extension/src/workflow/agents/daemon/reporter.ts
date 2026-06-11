import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { DaemonConnection } from "./client.ts";
import { PROTOCOL_VERSION } from "./frames.ts";

const FLUSH_DELAY_MS = 50;

type AgentMessageContentPart = {
	type?: string;
	text?: unknown;
};

type AgentMessage = {
	role?: string;
	content?: unknown;
};

function extractTextFromContent(content: unknown): string {
	if (!Array.isArray(content)) return typeof content === "string" ? content : "";
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

	pi.on("tool_execution_start", (event) => {
		const payload = event as { toolCallId?: unknown; toolName?: unknown };
		void sendTelemetry("tool_execution_start", {
			toolCallId: typeof payload.toolCallId === "string" ? payload.toolCallId : null,
			toolName: typeof payload.toolName === "string" ? payload.toolName : null,
		});
	});

	pi.on("tool_execution_end", (event) => {
		const payload = event as { toolCallId?: unknown; toolName?: unknown; isError?: unknown };
		void sendTelemetry("tool_execution_end", {
			toolCallId: typeof payload.toolCallId === "string" ? payload.toolCallId : null,
			toolName: typeof payload.toolName === "string" ? payload.toolName : null,
			isError: typeof payload.isError === "boolean" ? payload.isError : null,
		});
	});

	pi.on("turn_end", (event) => {
		const payload = event as { turnIndex?: unknown };
		void sendTelemetry("turn_end", {
			turnIndex: typeof payload.turnIndex === "number" ? payload.turnIndex : null,
		});
	});

	pi.on("agent_end", async (event) => {
		try {
			const payload = event as { messages?: unknown };
			const result = extractLastAssistantMessage(payload.messages);
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
