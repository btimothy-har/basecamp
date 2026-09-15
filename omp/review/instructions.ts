import type { ContextEvent, ContextEventResult, ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

export const REVIEW_PRESENTATION_INSTRUCTIONS = `<system-reminder>
After every native OMP reviewer task has completed:

1. Validate each proposed finding against the reviewed code and discard false positives.
2. Semantically deduplicate findings that describe the same underlying defect.
3. Form one final overall correctness judgment and explanation.
4. Call \`review_findings\` exactly once with the reviewed scope and final consolidated findings, including an empty findings array when none remain.
5. Read the \`artifact://\` URI returned by \`review_findings\` before continuing, then incorporate the user's submitted feedback.

Reviewer subagents must continue returning findings through their native structured yield. They must not call \`review_findings\`.
</system-reminder>`;

export function isNativeReviewRequest(prompt: string): boolean {
	const normalized = prompt.trimStart();
	return (
		normalized.startsWith("## Code Review Request\n") &&
		normalized.includes("task") &&
		normalized.includes('agent: "reviewer"')
	);
}

function messageText(message: ContextEvent["messages"][number]): string {
	if (!("role" in message) || message.role !== "user") return "";
	if (typeof message.content === "string") return message.content;
	return message.content
		.filter((part) => part.type === "text")
		.map((part) => part.text)
		.join("\n");
}

export function addReviewPresentationInstructions(event: ContextEvent): ContextEventResult | undefined {
	let latestUserIndex = -1;
	for (let index = event.messages.length - 1; index >= 0; index -= 1) {
		if (messageText(event.messages[index]!) !== "") {
			latestUserIndex = index;
			break;
		}
	}
	if (latestUserIndex < 0 || !isNativeReviewRequest(messageText(event.messages[latestUserIndex]!))) return;

	const alreadyPresented = event.messages
		.slice(latestUserIndex + 1)
		.some((message) => "role" in message && message.role === "toolResult" && message.toolName === "review_findings");
	if (alreadyPresented) return;

	const messages = [...event.messages];
	messages.splice(latestUserIndex + 1, 0, {
		role: "user",
		content: REVIEW_PRESENTATION_INSTRUCTIONS,
		synthetic: true,
		timestamp: 0,
	});
	return { messages };
}

export default function registerReviewInstructions(pi: ExtensionAPI): void {
	pi.on("context", addReviewPresentationInstructions);
}
