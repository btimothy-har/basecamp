import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { buildUserContext, recentUserMessages } from "#core/session/user-context.ts";

function entry(message: unknown): SessionEntry {
	return { type: "message", message } as unknown as SessionEntry;
}

describe("buildUserContext", () => {
	it("includes only user text plus the pending prompt and excludes assistant text", () => {
		const context = buildUserContext(
			[
				entry({ role: "user", content: "Please harden title generation." }),
				entry({ role: "assistant", content: [{ type: "text", text: "I will inspect the title module." }] }),
			],
			"Add focused tests next.",
		);

		assert.match(context, /\[User\]\nPlease harden title generation\./);
		assert.doesNotMatch(context, /\[Assistant\]/);
		assert.doesNotMatch(context, /I will inspect the title module/);
		assert.match(context, /\[Pending User Prompt\]\nAdd focused tests next\./);
	});

	it("excludes assistant tool calls and tool results entirely", () => {
		const context = buildUserContext([
			entry({ role: "user", content: "Run the title tests." }),
			entry({
				role: "assistant",
				content: [
					{ type: "text", text: "Running tests." },
					{ type: "toolCall", name: "bash", arguments: { command: "npm test" } },
				],
			}),
			entry({
				role: "toolResult",
				toolName: "bash",
				isError: true,
				content: [{ type: "text", text: "SECRET raw tool output" }],
			}),
		]);

		assert.equal(context, "[User]\nRun the title tests.");
		assert.doesNotMatch(context, /\[Tool:bash\]/);
		assert.doesNotMatch(context, /SECRET raw tool output/);
	});

	it("includes the first 3 and most recent 3 user messages in order with the pending prompt", () => {
		const entries: SessionEntry[] = [
			...Array.from({ length: 35 }, (_, index) => entry({ role: "user", content: `message ${index + 1}` })),
			{ type: "summary", text: "non-message entry" } as unknown as SessionEntry,
			{ type: "checkpoint", text: "another non-message entry" } as unknown as SessionEntry,
		];

		const context = buildUserContext(entries, "pending prompt after recent messages");

		assert.match(context, /\bmessage 1\b/);
		assert.match(context, /\bmessage 3\b/);
		assert.match(context, /\bmessage 33\b/);
		assert.match(context, /\bmessage 35\b/);
		assert.doesNotMatch(context, /\bmessage 4\b/);
		assert.doesNotMatch(context, /\bmessage 32\b/);
		assert.ok(context.indexOf("message 1") < context.indexOf("message 33"));
		assert.match(context, /\[Pending User Prompt\]\npending prompt after recent messages/);
	});

	it("never duplicates a user message across the first/recent boundary", () => {
		for (const count of [4, 5, 6, 7, 8]) {
			const entries = Array.from({ length: count }, (_, index) => entry({ role: "user", content: `m${index + 1}` }));

			const context = buildUserContext(entries);
			const selected = [...context.matchAll(/\bm(\d+)\b/g)].map((match) => match[1]);

			assert.equal(selected.length, new Set(selected).size, `duplication at count=${count}`);
			assert.equal(selected.length, count <= 6 ? count : 6, `unexpected selection size at count=${count}`);
		}
	});

	it("reduces fenced code and log-like text while keeping overall output bounded", () => {
		const fencedCode = `Before code\n\`\`\`ts\n${"const secret = 1;\n".repeat(500)}\`\`\`\nAfter code`;
		const logs = Array.from({ length: 500 }, (_, index) => `2026-05-04T12:00:00 INFO noisy line ${index}`).join("\n");
		const repeatedEntries = Array.from({ length: 20 }, () =>
			entry({ role: "user", content: `${fencedCode}\n${logs}` }),
		);
		const context = buildUserContext(repeatedEntries, "Final pending prompt");

		assert.ok(context.length <= 8_000, `context length ${context.length} exceeded bound`);
		assert.match(context, /\[fenced code block omitted\]/);
		assert.match(context, /\[\d+ log-like lines omitted\]/);
		assert.doesNotMatch(context, /const secret = 1/);
	});
});

describe("recentUserMessages", () => {
	it("returns only user-role messages, most-recent-last, respecting the limit", () => {
		const entries = [
			{ type: "message", message: { role: "user", content: "first" } },
			{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "reply" }] } },
			{ type: "custom", data: {} },
			{ type: "message", message: { role: "user", content: [{ type: "text", text: "second" }] } },
			{
				type: "message",
				message: {
					role: "user",
					content: [
						{ type: "text", text: "third " },
						{ type: "text", text: "part" },
					],
				},
			},
		];
		assert.deepEqual(recentUserMessages(entries as SessionEntry[]), ["first", "second", "third part"]);
		assert.deepEqual(recentUserMessages(entries as SessionEntry[], 2), ["second", "third part"]);
		assert.deepEqual(recentUserMessages(entries as SessionEntry[], 1), ["third part"]);
	});

	// The continuation guard sends these on essentially every stop, so one pasted log
	// would otherwise be replayed in full for as long as it stays in the window.
	it("bounds each message so a large paste cannot dominate the prompt", () => {
		const entries = [{ type: "message", message: { role: "user", content: "x".repeat(50_000) } }];

		const [only] = recentUserMessages(entries as SessionEntry[]);

		assert.ok(only);
		assert.ok(only.length < 1_300, `expected a bounded message, got ${only.length} chars`);
		assert.match(only, /…$/);
	});

	it("defaults to the five most recent user messages", () => {
		const entries = Array.from({ length: 7 }, (_, i) => ({
			type: "message",
			message: { role: "user", content: `msg-${i}` },
		}));
		assert.deepEqual(recentUserMessages(entries as SessionEntry[]), ["msg-2", "msg-3", "msg-4", "msg-5", "msg-6"]);
	});
});
