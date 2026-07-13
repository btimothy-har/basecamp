import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ADJECTIVES, NOUNS } from "../../naming/index.ts";
import { buildAgentHandle, buildDeterministicAgentHandle } from "../handles.ts";

// adjective-noun-<6 lowercase hex>. Structural, not a golden string, so it guards
// the handle format + determinism contract without breaking on benign bank edits.
const HANDLE_SHAPE = /^[a-z]+-[a-z]+-[0-9a-f]{6}$/;

function assertHandleShape(handle: string): void {
	assert.match(handle, HANDLE_SHAPE);
	const [adjective, noun] = handle.split("-");
	assert.ok(ADJECTIVES.includes(adjective ?? ""), `expected an adjective, got ${adjective}`);
	assert.ok(NOUNS.includes(noun ?? ""), `expected a noun, got ${noun}`);
}

describe("buildAgentHandle", () => {
	it("produces an adjective-noun-hex6 handle", () => {
		for (let i = 0; i < 16; i += 1) {
			assertHandleShape(buildAgentHandle());
		}
	});

	it("varies between calls (the hex id carries uniqueness)", () => {
		const handles = new Set(Array.from({ length: 8 }, () => buildAgentHandle()));
		assert.ok(handles.size > 1);
	});
});

describe("buildDeterministicAgentHandle", () => {
	it("produces an adjective-noun-hex6 handle", () => {
		assertHandleShape(buildDeterministicAgentHandle("node-abc"));
	});

	it("is stable for the same seed", () => {
		assert.equal(buildDeterministicAgentHandle("node-abc"), buildDeterministicAgentHandle("node-abc"));
	});

	it("differs for different seeds", () => {
		assert.notEqual(buildDeterministicAgentHandle("node-abc"), buildDeterministicAgentHandle("node-xyz"));
	});
});
