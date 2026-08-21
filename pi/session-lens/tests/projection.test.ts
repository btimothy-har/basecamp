import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Usage } from "@earendil-works/pi-ai";
import type { SessionEntry, SessionMessageEntry } from "@earendil-works/pi-coding-agent";
import { projectVisibleSession } from "#session-lens/projection.ts";

const usage: Usage = {
	input: 1,
	output: 1,
	cacheRead: 0,
	cacheWrite: 0,
	totalTokens: 2,
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

function entry(id: string, parentId: string | null, message: SessionMessageEntry["message"]): SessionMessageEntry {
	return { type: "message", id, parentId, timestamp: "2026-08-22T00:00:00Z", message };
}

describe("projectVisibleSession", () => {
	it("projects the active compacted branch without hidden, image, or thinking content", () => {
		const longToolResult = "result ".repeat(400);
		const longToolArgument = `${"file content ".repeat(400)}UNBOUNDED_TAIL`;
		const entries: SessionEntry[] = [
			entry("u-old", null, { role: "user", content: "old detail that was compacted", timestamp: 1 }),
			entry("a-old", "u-old", {
				role: "assistant",
				content: [{ type: "text", text: "old answer that was compacted" }],
				api: "anthropic-messages",
				provider: "anthropic",
				model: "old-model",
				usage,
				stopReason: "stop",
				timestamp: 2,
			}),
			entry("u-kept", "a-old", {
				role: "user",
				content: [
					{ type: "text", text: "retained visible request" },
					{ type: "image", data: "private-image-data", mimeType: "image/png" },
				],
				timestamp: 3,
			}),
			{
				type: "compaction",
				id: "compact",
				parentId: "u-kept",
				timestamp: "2026-08-22T00:00:04Z",
				summary: "Earlier work reached a stable plan.",
				firstKeptEntryId: "u-kept",
				tokensBefore: 100,
			},
			{
				type: "custom_message",
				id: "hidden",
				parentId: "compact",
				timestamp: "2026-08-22T00:00:05Z",
				customType: "hidden-context",
				content: "hidden extension instruction",
				display: false,
			},
			{
				type: "custom_message",
				id: "visible-custom",
				parentId: "hidden",
				timestamp: "2026-08-22T00:00:05Z",
				customType: "visible-context",
				content: "visible extension context",
				display: true,
			},
			entry("a-visible", "visible-custom", {
				role: "assistant",
				content: [
					{ type: "thinking", thinking: "private chain of thought" },
					{ type: "text", text: "Visible decision and caveat." },
					{ type: "toolCall", id: "call-1", name: "read", arguments: { path: "visible.ts" } },
					{ type: "toolCall", id: "call-2", name: "write", arguments: { content: longToolArgument } },
				],
				api: "anthropic-messages",
				provider: "anthropic",
				model: "current-model",
				usage,
				stopReason: "toolUse",
				timestamp: 6,
			}),
			entry("tool", "a-visible", {
				role: "toolResult",
				toolCallId: "call-1",
				toolName: "read",
				content: [
					{ type: "text", text: longToolResult },
					{ type: "image", data: "tool-image-data", mimeType: "image/png" },
				],
				isError: false,
				timestamp: 7,
			}),
			entry("u-string", "tool", { role: "user", content: "visible string message", timestamp: 8 }),
			entry("abandoned", "a-old", { role: "user", content: "abandoned sibling branch", timestamp: 9 }),
		];

		const projected = projectVisibleSession(entries, "u-string");

		assert.match(projected, /Earlier work reached a stable plan/);
		assert.match(projected, /retained visible request/);
		assert.match(projected, /visible extension context/);
		assert.match(projected, /Visible decision and caveat/);
		assert.match(projected, /visible string message/);
		assert.match(projected, /read\(path="visible\.ts"\)/);
		assert.match(projected, /write\(truncated_arguments=/);
		assert.match(projected, /more characters truncated/);
		assert.doesNotMatch(projected, /UNBOUNDED_TAIL/);
		assert.ok(projected.length < longToolArgument.length);
		assert.doesNotMatch(projected, /old detail|old answer|abandoned sibling/);
		assert.doesNotMatch(projected, /hidden extension instruction|private chain of thought/);
		assert.doesNotMatch(projected, /private-image-data|tool-image-data/);
	});

	it("returns empty text when the active branch has no context messages", () => {
		assert.equal(projectVisibleSession([], null), "");
	});
});
