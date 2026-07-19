import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import { buildUserContext } from "../user-context.ts";

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
