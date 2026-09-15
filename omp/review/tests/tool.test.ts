import { describe, expect, test } from "bun:test";
import { type as arktype } from "@oh-my-pi/omptype";
import type { ExtensionAPI, ExtensionContext, Theme, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import type { ReviewArtifactV1, ReviewFindingsInput } from "../schema.ts";
import registerReviewTool, { type ReviewToolDetails } from "../tool.ts";
import { DOWN, ENTER, ESC, navigatorHarness, SPACE, type } from "./support/navigator-driver.ts";

interface SavedArtifact {
	content: string;
	toolType: string;
}

function reviewInput(findings: ReviewFindingsInput["findings"] = []): ReviewFindingsInput {
	return {
		scope: "main...HEAD",
		overall_correctness: findings.length === 0 ? "correct" : "incorrect",
		explanation: findings.length === 0 ? "No validated findings." : "Validated findings remain.",
		confidence: 0.9,
		findings,
	};
}

function finding(overrides: Partial<ReviewFindingsInput["findings"][number]> = {}) {
	return {
		title: "Finding title",
		body: "Finding body",
		priority: 2 as const,
		confidence: 0.8,
		file_path: "src/app.ts",
		line_start: 10,
		line_end: 12,
		...overrides,
	};
}

function toolHarness(
	ui: ExtensionContext["ui"],
	mode: ExtensionContext["mode"],
	artifactPath: string | null = "/tmp/42.code-review.log",
) {
	let definition: ToolDefinition | undefined;
	const saved: SavedArtifact[] = [];
	const api = {
		arktype,
		registerTool(tool: ToolDefinition): void {
			definition = tool;
		},
	} as unknown as ExtensionAPI;
	registerReviewTool(api);
	if (!definition) throw new Error("review_findings was not registered");
	const tool = definition;
	const ctx = {
		cwd: "/repo",
		mode,
		ui,
		sessionManager: {
			async saveArtifact(content: string, toolType: string): Promise<string> {
				saved.push({ content, toolType });
				return "42";
			},
			async getArtifactPath(): Promise<string | null> {
				return artifactPath;
			},
		},
	} as unknown as ExtensionContext;
	return {
		definition: tool,
		saved,
		async execute(input: ReviewFindingsInput, signal?: AbortSignal) {
			return tool.execute("call-1", input, signal, undefined, ctx);
		},
	};
}

function savedReview(saved: SavedArtifact[]): ReviewArtifactV1 {
	const artifact = saved[0];
	if (!artifact) throw new Error("review artifact was not saved");
	return JSON.parse(artifact.content) as ReviewArtifactV1;
}

describe("review_findings", () => {
	test("saves submitted comments and returns only the artifact instruction", async () => {
		const ui = navigatorHarness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("fix before merge"), ENTER, ESC),
			(send) => send("s"),
		]);
		const harness = toolHarness(ui as ExtensionContext["ui"], "tui");

		const result = await harness.execute(reviewInput([finding()]));

		expect(result.content).toEqual([{ type: "text", text: "Read artifact://42 before continuing." }]);
		expect(harness.saved[0]?.toolType).toBe("code-review");
		expect(savedReview(harness.saved).feedback_status).toBe("submitted");
		expect(savedReview(harness.saved).findings[0]?.feedback.comment).toBe("fix before merge");
		expect(result.details).toMatchObject({
			artifactPersistent: true,
			artifactRef: "artifact://42",
			commentedCount: 1,
		});
	});

	test("discards draft comments when the navigator is cancelled", async () => {
		const ui = navigatorHarness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("draft"), ENTER, ESC),
			(send) => send(ESC),
		]);
		const harness = toolHarness(ui as ExtensionContext["ui"], "tui");

		await harness.execute(reviewInput([finding()]));

		const artifact = savedReview(harness.saved);
		expect(artifact.feedback_status).toBe("cancelled");
		expect(artifact.findings[0]?.feedback.comment).toBeNull();
	});

	test("forwards cancellation to the navigator and does not persist after abort", async () => {
		const controller = new AbortController();
		let receivedSignal: AbortSignal | undefined;
		const ui = {
			custom: (_factory: unknown, options?: { signal?: AbortSignal }) => {
				receivedSignal = options?.signal;
				controller.abort();
				return Promise.reject(controller.signal.reason);
			},
		} as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "tui");

		await expect(harness.execute(reviewInput([finding()]), controller.signal)).rejects.toBeDefined();

		expect(receivedSignal).toBe(controller.signal);
		expect(harness.saved).toHaveLength(0);
	});

	test("saves headless findings with unavailable feedback", async () => {
		const ui = { custom: () => Promise.reject(new Error("must not open")) } as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "print");

		await harness.execute(reviewInput([finding({ line_end: 30 })]));

		expect(savedReview(harness.saved).feedback_status).toBe("unavailable");
	});

	test("returns complete review JSON inline when the artifact is not persistent", async () => {
		const ui = { custom: () => Promise.reject(new Error("must not open")) } as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "print", null);

		const result = await harness.execute(reviewInput([finding({ file_path: "/repo/src/app.ts" })]));
		const text = result.content[0]?.type === "text" ? result.content[0].text : "";

		expect(result.details).toMatchObject({ artifactPersistent: false, artifactRef: "artifact://42" });
		expect(text).toContain('"schema_version": 1');
		expect(JSON.parse(text) as ReviewArtifactV1).toMatchObject({
			findings: [{ file_path: "src/app.ts" }],
		});
	});

	test("skips navigation for an empty review", async () => {
		const ui = { custom: () => Promise.reject(new Error("must not open")) } as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "tui");

		const result = await harness.execute(reviewInput());

		expect(savedReview(harness.saved).feedback_status).toBe("not_required");
		expect(result.details).toMatchObject({ findingCount: 0, feedbackStatus: "not_required" });
	});

	test("replays a passive result from persisted details", async () => {
		const harness = toolHarness({} as ExtensionContext["ui"], "print");
		const result = await harness.execute(reviewInput([finding({ priority: 1 })]));
		const theme = {
			fg: (_color: string, text: string) => text,
			bold: (text: string) => text,
		} as unknown as Theme;

		const rendered = harness.definition.renderResult?.(
			result as { content: typeof result.content; details: ReviewToolDetails },
			{ expanded: false, isPartial: false },
			theme,
		);

		expect(rendered?.render(100).join("\n")).toContain("Interactive review unavailable");
		expect(rendered?.render(100).join("\n")).toContain("P0 0   P1 1   P2 0   P3 0");
		expect(rendered?.render(100).join("\n")).toContain("artifact://42");
	});
});
