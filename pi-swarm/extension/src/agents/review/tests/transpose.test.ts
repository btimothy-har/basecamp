import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { AssistantMessage, Model } from "@earendil-works/pi-ai";
import { type TransposeDeps, transposeReport } from "../transpose.ts";

const fakeModel: Model<any> = {
	id: "fake-model",
	name: "Fake Model",
	api: "openai-responses",
	provider: "fake-provider",
	baseUrl: "https://example.test",
	reasoning: false,
	input: ["text"],
	cost: {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
	},
	contextWindow: 128_000,
	maxTokens: 4096,
};

const usage = {
	input: 0,
	output: 0,
	cacheRead: 0,
	cacheWrite: 0,
	totalTokens: 0,
	cost: {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
		total: 0,
	},
};

function assistantMessage(
	content: AssistantMessage["content"],
	stopReason: AssistantMessage["stopReason"] = "toolUse",
): AssistantMessage {
	return {
		role: "assistant",
		content,
		api: "openai-responses",
		provider: "fake-provider",
		model: "fake-model",
		usage,
		stopReason,
		timestamp: 123,
	};
}

function toolCall(
	argumentsValue: Record<string, unknown>,
	name = "report_findings",
): AssistantMessage["content"][number] {
	return {
		type: "toolCall",
		id: "call-1",
		name,
		arguments: argumentsValue,
	};
}

describe("transposeReport", () => {
	it("extracts findings and stamps the given dimension", async () => {
		const complete: NonNullable<TransposeDeps["complete"]> = async (_model, context, options) => {
			assert.equal(context.systemPrompt?.includes("Call report_findings exactly once."), true);
			assert.deepEqual(
				context.messages.map((message) => message.content),
				["review prose only"],
			);
			assert.deepEqual(
				context.tools?.map((tool) => tool.name),
				["report_findings"],
			);
			assert.deepEqual(options?.toolChoice, { type: "function", function: { name: "report_findings" } });

			return assistantMessage([
				toolCall({
					findings: [
						{
							severity: "high",
							file: "src/app.ts",
							lineStart: 12,
							lineEnd: 14,
							title: "Incorrect common path result",
							detail: "The common path returns stale data.",
							remediation: "Refresh the cache before reading.",
						},
					],
				}),
			]);
		};

		assert.deepEqual(await transposeReport("review prose only", "general", { model: fakeModel, auth: {}, complete }), [
			{
				dimension: "general",
				severity: "high",
				file: "src/app.ts",
				lineStart: 12,
				lineEnd: 14,
				title: "Incorrect common path result",
				detail: "The common path returns stale data.",
				remediation: "Refresh the cache before reading.",
			},
		]);
	});

	it("returns an empty array for a clean report", async () => {
		const complete: NonNullable<TransposeDeps["complete"]> = async () => assistantMessage([toolCall({ findings: [] })]);

		assert.deepEqual(await transposeReport("No findings.", "testing", { model: fakeModel, auth: {}, complete }), []);
	});

	it("throws when the model returns an error stop reason", async () => {
		const complete: NonNullable<TransposeDeps["complete"]> = async () => ({
			...assistantMessage([], "error"),
			errorMessage: "provider failed",
		});

		await assert.rejects(
			() => transposeReport("report", "security", { model: fakeModel, auth: {}, complete }),
			/provider failed/,
		);
	});

	it("throws when there is no report_findings tool call", async () => {
		const complete: NonNullable<TransposeDeps["complete"]> = async () =>
			assistantMessage([toolCall({ findings: [] }, "other_tool")]);

		await assert.rejects(
			() => transposeReport("report", "docs", { model: fakeModel, auth: {}, complete }),
			/valid report_findings tool call/,
		);
	});

	it("throws when report_findings args fail validation", async () => {
		const complete: NonNullable<TransposeDeps["complete"]> = async () =>
			assistantMessage([
				toolCall({
					findings: [
						{
							severity: "moderate",
							file: "src/app.ts",
							lineStart: 1,
							lineEnd: 1,
							title: "Invalid severity",
							detail: "Severity must be canonical.",
							remediation: null,
						},
					],
				}),
			]);

		await assert.rejects(
			() => transposeReport("report", "clarity", { model: fakeModel, auth: {}, complete }),
			/valid report_findings tool call/,
		);
	});
});
