import { describe, expect, test } from "bun:test";
import type { ContextEvent, ContextEventResult, ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerReviewInstructions, {
	addReviewPresentationInstructions,
	isNativeReviewRequest,
	REVIEW_PRESENTATION_INSTRUCTIONS,
} from "../instructions.ts";
import { buildReviewRequest } from "../request.ts";

type Handler = (event: ContextEvent) => ContextEventResult | undefined;

const reviewPrompt =
	'## Code Review Request\n\n### Distribution Guidelines\nUse the `task` tool with `agent: "reviewer"`.';

function contextEvent(messages: unknown[]): ContextEvent {
	return { type: "context", messages } as ContextEvent;
}

function instructionHandler(): Handler {
	let handler: Handler | undefined;
	const api = {
		on(event: string, registered: Handler): void {
			if (event === "context") handler = registered;
		},
	} as unknown as ExtensionAPI;
	registerReviewInstructions(api);
	if (!handler) throw new Error("context handler was not registered");
	return handler;
}

describe("Basecamp review instructions", () => {
	test("recognizes the review request protocol marker", () => {
		expect(isNativeReviewRequest(reviewPrompt)).toBe(true);
		expect(isNativeReviewRequest('Review this change with agent: "reviewer" and task.')).toBe(false);
	});

	test("injects the presentation contract after the active review prompt", () => {
		const result = addReviewPresentationInstructions(
			contextEvent([
				{ role: "user", content: reviewPrompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
			]),
		);

		expect(result?.messages).toHaveLength(3);
		expect(result?.messages?.[1]).toEqual({
			role: "user",
			content: REVIEW_PRESENTATION_INSTRUCTIONS,
			synthetic: true,
			timestamp: 0,
		});
	});
	test("keeps the chair contract active for generated requests until presentation succeeds", () => {
		const prompt = buildReviewRequest({
			kind: "custom",
			cwd: "/worktrees/widgets",
			instructions: "Review main against this branch.",
		});
		const handler = instructionHandler();

		const active = handler(
			contextEvent([
				{ role: "user", content: prompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
			]),
		);
		expect(active?.messages?.[1]).toMatchObject({ content: REVIEW_PRESENTATION_INSTRUCTIONS });

		const complete = handler(
			contextEvent([
				{ role: "user", content: prompt, timestamp: 1 },
				{ role: "toolResult", toolName: "review_findings", isError: false, content: [], timestamp: 2 },
			]),
		);
		expect(complete).toBeUndefined();
	});


	test("keeps instructions active after reviewer tool results", () => {
		const result = instructionHandler()(
			contextEvent([
				{ role: "user", content: reviewPrompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
				{ role: "toolResult", content: [], timestamp: 3 },
			]),
		);

		expect(result?.messages?.[1]).toMatchObject({ content: REVIEW_PRESENTATION_INSTRUCTIONS });
	});

	test("stops injecting after review_findings has presented the review", () => {
		const result = instructionHandler()(
			contextEvent([
				{ role: "user", content: reviewPrompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
				{ role: "toolResult", toolName: "review_findings", isError: false, content: [], timestamp: 3 },
			]),
		);

		expect(result).toBeUndefined();
	});

	test("keeps instructions active after review_findings fails", () => {
		const result = instructionHandler()(
			contextEvent([
				{ role: "user", content: reviewPrompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
				{ role: "toolResult", toolName: "review_findings", isError: true, content: [], timestamp: 3 },
			]),
		);

		expect(result?.messages?.[1]).toMatchObject({ content: REVIEW_PRESENTATION_INSTRUCTIONS });
	});

	test("does not revive instructions from a historical review", () => {
		const result = instructionHandler()(
			contextEvent([
				{ role: "user", content: reviewPrompt, timestamp: 1 },
				{ role: "assistant", content: [], timestamp: 2 },
				{ role: "user", content: "Implement the accepted changes.", timestamp: 3 },
			]),
		);

		expect(result).toBeUndefined();
	});
});
