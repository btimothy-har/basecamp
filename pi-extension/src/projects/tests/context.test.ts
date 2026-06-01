import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { CatalogItem } from "../../platform/catalog.ts";
import { buildMemoryGuidance } from "../context.ts";

function tool(name: string): CatalogItem {
	return { type: "tools", name, description: "" };
}

describe("buildMemoryGuidance", () => {
	it("returns null when no memory tools are present", () => {
		assert.equal(buildMemoryGuidance([tool("read"), tool("bash")]), null);
	});

	it("emits the instruction block when memory tools are present", () => {
		const block = buildMemoryGuidance([tool("memory_search"), tool("session_search"), tool("memory_remember")]);
		assert.ok(block);
		assert.match(block, /^# Memory/);
		assert.match(block, /memory_search/);
		assert.match(block, /session_search/);
		assert.match(block, /memory_remember/);
	});

	it("emits when only one of the memory tools is present", () => {
		assert.ok(buildMemoryGuidance([tool("session_search")]));
		assert.ok(buildMemoryGuidance([tool("memory_search")]));
	});
});
