import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { PROTOCOL_VERSION } from "../../hub/protocol/index.ts";
import type { DaemonConnection } from "./client.ts";
import {
	appendText,
	asRecord,
	displayText,
	eventHasThinking,
	extractLastAssistantMessage,
	extractMessageRole,
	extractSkillName,
	extractToolInput,
	extractToolName,
	extractVisibleTextFromMessageEvent,
	messageText,
	safeString,
	summarizeToolInput,
	summarizeToolResult,
} from "./event-summaries.ts";
import {
	BASECAMP_RUN_ATTEMPT,
	BASECAMP_RUN_RESULT_PATH,
	BASECAMP_RUNNER_MANAGED_RESULT,
	upsertRunResultAttempt,
} from "./run-result.ts";

const FLUSH_DELAY_MS = 50;

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function runnerManagedResultPath(): string | null {
	if (process.env[BASECAMP_RUNNER_MANAGED_RESULT] !== "1") return null;
	const filePath = process.env[BASECAMP_RUN_RESULT_PATH];
	if (!filePath) throw new Error("missing runner-managed result path");
	return filePath;
}

function runnerManagedAttempt(): number {
	const rawAttempt = process.env[BASECAMP_RUN_ATTEMPT];
	if (!rawAttempt?.trim()) throw new Error("invalid runner-managed result attempt");
	const attempt = Number(rawAttempt);
	if (!Number.isInteger(attempt)) throw new Error("invalid runner-managed result attempt");
	return attempt;
}

export function registerDaemonReporter(
	pi: ExtensionAPI,
	options: {
		awaitConnection: () => Promise<DaemonConnection | null>;
		runId: string;
		agentId: string;
	},
): void {
	const { awaitConnection, runId, agentId } = options;
	const reportToken = process.env.BASECAMP_REPORT_TOKEN;
	if (!reportToken) return;

	let assistantBuffer = "";
	let thinkingReported = false;
	let activeMessageRole: string | null = null;

	const sendTelemetry = async (kind: string, payload: Record<string, unknown>): Promise<void> => {
		try {
			const connection = await awaitConnection();
			if (!connection) return;
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
		const text = messageText(assistantBuffer);
		assistantBuffer = "";
		const snippet = displayText(text);
		if (!text || !snippet) return;
		sendDisplayTelemetry("assistant_output", {
			category: "assistant",
			label: "assistant",
			snippet,
			text,
		});
	};

	pi.on("tool_execution_start", (event) => {
		const toolName = extractToolName(event);
		const input = extractToolInput(event);
		void sendTelemetry("tool_execution_start", {
			toolCallId: safeString(asRecord(event)?.toolCallId) ?? null,
			toolName,
		});

		const snippet = summarizeToolInput(toolName, input);
		const payload: Record<string, unknown> = {
			category: "tool",
			label: toolName ?? "tool",
			snippet: snippet ?? (toolName ? `${toolName} called` : "tool called"),
			toolName,
		};
		const skillName = extractSkillName(toolName, input);
		if (skillName) payload.skillName = skillName;
		sendDisplayTelemetry("tool_call", payload);
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
		assistantBuffer = appendText(assistantBuffer, extractVisibleTextFromMessageEvent(event));
	});

	pi.on("message_end", (event) => {
		const role = extractMessageRole(event) ?? activeMessageRole;
		if (role && role !== "assistant") {
			activeMessageRole = null;
			return;
		}
		if (eventHasThinking(event)) sendThinkingMarker();
		const fullText = extractVisibleTextFromMessageEvent(event);
		if (fullText) assistantBuffer = fullText;
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

			const runResultPath = runnerManagedResultPath();
			if (runResultPath) {
				await upsertRunResultAttempt(
					runResultPath,
					{ run_id: runId, agent_id: agentId },
					{
						attempt: runnerManagedAttempt(),
						status: "ok",
						result,
						error: null,
					},
				);
				await sleep(FLUSH_DELAY_MS);
				return;
			}

			const connection = await awaitConnection();
			if (!connection) return;
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
