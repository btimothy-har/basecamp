import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { registerBashReviewer } from "../reviewer/index.ts";

describe("bash reviewer", () => {
	it("imports the reviewer module", () => {
		assert.equal(typeof registerBashReviewer, "function");
	});
});
