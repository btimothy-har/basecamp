import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { withHerdrBlocked } from "../herdr.ts";

function emitter(events: unknown[]): Pick<ExtensionAPI, "events"> {
	return {
		events: {
			emit: (channel: string, data: unknown) => {
				events.push({ channel, data });
			},
		},
	} as unknown as Pick<ExtensionAPI, "events">;
}

describe("withHerdrBlocked", () => {
	it("brackets the operation and returns its result", async () => {
		const events: unknown[] = [];
		const result = await withHerdrBlocked(emitter(events), "Waiting for input", async () => {
			events.push("operation");
			return 42;
		});

		assert.equal(result, 42);
		assert.deepEqual(events, [
			{ channel: "herdr:blocked", data: { active: true, label: "Waiting for input" } },
			"operation",
			{ channel: "herdr:blocked", data: { active: false } },
		]);
	});

	it("clears blocked state when the operation rejects", async () => {
		const events: unknown[] = [];

		await assert.rejects(
			() =>
				withHerdrBlocked(emitter(events), "Waiting for input", async () => {
					throw new Error("failed");
				}),
			/failed/,
		);
		assert.deepEqual(events, [
			{ channel: "herdr:blocked", data: { active: true, label: "Waiting for input" } },
			{ channel: "herdr:blocked", data: { active: false } },
		]);
	});
});
