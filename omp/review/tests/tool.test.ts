import { describe, expect, test } from "bun:test";
import { type as arktype } from "@oh-my-pi/omptype";
import type { ExtensionAPI, ExtensionContext, Theme, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import type { ReviewArtifactV2, ReviewFindingsInput } from "../schema.ts";
import registerReviewTool, { type ReviewToolDetails } from "../tool.ts";
import { DOWN, ENTER, ESC, navigatorHarness, SPACE, type } from "./support/navigator-driver.ts";

interface SavedArtifact {
	content: string;
	toolType: string;
}

interface SavedBlob {
	data: Buffer;
	extension: string | undefined;
}

const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

function reviewInput(findings: ReviewFindingsInput["findings"] = []): ReviewFindingsInput {
	return {
		scope: "main...HEAD",
		overall_correctness: findings.length === 0 ? "correct" : "incorrect",
		explanation: findings.length === 0 ? "No validated findings." : "Validated findings remain.",
		recommendation: findings.length === 0 ? "Merge after CI passes." : "Fix the validated findings before merging.",
		confidence: 0.9,
		findings,
	};
}

function finding(overrides: Partial<ReviewFindingsInput["findings"][number]> = {}) {
	return {
		title: "Finding title",
		body: "Finding body",
		recommendation: "Apply the focused fix.",
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
	artifactsDir: string | null = "/tmp/artifacts",
) {
	let definition: ToolDefinition | undefined;
	const saved: SavedArtifact[] = [];
	const blobs: SavedBlob[] = [];
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
		cwd: process.cwd(),
		mode,
		ui,
		sessionManager: {
			getArtifactsDir(): string | null {
				return artifactsDir;
			},
			async saveArtifact(content: string, toolType: string): Promise<string> {
				saved.push({ content, toolType });
				return "42";
			},
			async putBlob(data: Buffer, options?: { extension?: string }) {
				blobs.push({ data, extension: options?.extension });
				return { displayPath: "/tmp/blobs/review.json" };
			},
		},
	} as unknown as ExtensionContext;
	return {
		definition: tool,
		saved,
		blobs,
		async execute(input: ReviewFindingsInput, signal?: AbortSignal) {
			return tool.execute("call-1", input, signal, undefined, ctx);
		},
	};
}

function savedReview(saved: SavedArtifact[]): ReviewArtifactV2 {
	const artifact = saved[0];
	if (!artifact) throw new Error("review artifact was not saved");
	return JSON.parse(artifact.content) as ReviewArtifactV2;
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
		expect(savedReview(harness.saved).recommendation).toBe("Fix the validated findings before merging.");
		expect(savedReview(harness.saved).findings[0]?.recommendation).toBe("Apply the focused fix.");
		expect(result.details).toMatchObject({
			commentedCount: 1,
			reviewRef: "artifact://42",
			storage: "artifact",
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

	test("stores no-session reviews as readable JSON blobs", async () => {
		const ui = { custom: () => Promise.reject(new Error("must not open")) } as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "print", null);
		const absolutePath = `${process.cwd()}/review/tool.ts`;

		const result = await harness.execute(reviewInput([finding({ file_path: absolutePath })]));

		expect(result.content).toEqual([{ type: "text", text: 'Read "/tmp/blobs/review.json" before continuing.' }]);
		expect(result.details).toMatchObject({ reviewRef: "/tmp/blobs/review.json", storage: "blob" });
		expect(harness.blobs[0]?.extension).toBe("json");
		expect(JSON.parse(harness.blobs[0]!.data.toString()) as ReviewArtifactV2).toMatchObject({
			findings: [{ file_path: "omp/review/tool.ts" }],
		});
		expect(harness.saved).toHaveLength(0);
	});

	test("skips navigation for an empty review", async () => {
		const ui = { custom: () => Promise.reject(new Error("must not open")) } as unknown as ExtensionContext["ui"];
		const harness = toolHarness(ui, "tui");

		const result = await harness.execute(reviewInput());

		expect(savedReview(harness.saved).feedback_status).toBe("not_required");
		expect(result.details).toMatchObject({ findingCount: 0, feedbackStatus: "not_required" });
		const rendered = harness.definition.renderResult?.(
			result as { content: typeof result.content; details: ReviewToolDetails },
			{ expanded: false, isPartial: false },
			theme,
		);
		const output = rendered?.render(100).join("\n");
		expect(output).toContain("Review complete");
		expect(output).toContain("90% confidence");
		expect(output).toContain("No validated findings.");
		expect(output).toContain("Merge after CI passes.");
	});

	test("replays a passive result from persisted details", async () => {
		const harness = toolHarness({} as ExtensionContext["ui"], "print");
		const result = await harness.execute(reviewInput([finding({ priority: 1 })]));

		const rendered = harness.definition.renderResult?.(
			result as { content: typeof result.content; details: ReviewToolDetails },
			{ expanded: false, isPartial: false },
			theme,
		);

		expect(rendered?.render(100).join("\n")).toContain("Interactive review unavailable");
		expect(rendered?.render(100).join("\n")).toContain("P0 0   P1 1   P2 0   P3 0");
		expect(rendered?.render(100).join("\n")).toContain("90% confidence");
		expect(rendered?.render(100).join("\n")).toContain("Validated findings remain.");
		expect(rendered?.render(100).join("\n")).toContain("Fix the validated findings before merging.");
		expect(rendered?.render(100).join("\n")).toContain("artifact://42");
		const legacyDetails = { ...(result.details as ReviewToolDetails) } as Partial<ReviewToolDetails>;
		delete legacyDetails.explanation;
		delete legacyDetails.overallConfidence;
		delete legacyDetails.recommendation;
		const replayed = harness.definition.renderResult?.(
			{ content: result.content, details: legacyDetails as ReviewToolDetails },
			{ expanded: false, isPartial: false },
			theme,
		);
		const replayedOutput = replayed?.render(100).join("\n");
		expect(replayedOutput).not.toContain("NaN");
		expect(replayedOutput).not.toContain("undefined");
		expect(replayedOutput).toContain("artifact://42");
	});
});
