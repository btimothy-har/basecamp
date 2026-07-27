import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { isCopilotLaunch } from "#core/agent-mode/copilot.ts";

const originalArgv = process.argv;

afterEach(() => {
	process.argv = originalArgv;
});

function launchWith(...args: string[]): void {
	process.argv = ["node", "pi", ...args];
}

describe("copilot launch predicate", () => {
	it("is false when the flag is absent", () => {
		launchWith("--workstream");
		assert.equal(isCopilotLaunch(), false);
	});

	it("is true for a bare --copilot", () => {
		launchWith("--copilot");
		assert.equal(isCopilotLaunch(), true);
	});

	// Pi coerces a boolean flag to true whatever value it parses, so the =form has
	// to agree with Pi's parser rather than with the literal value.
	it("is true for --copilot=<value>, matching Pi's boolean coercion", () => {
		launchWith("--copilot=false");
		assert.equal(isCopilotLaunch(), true);
	});

	it("does not match a longer flag that merely starts with --copilot", () => {
		launchWith("--copilots");
		assert.equal(isCopilotLaunch(), false);
	});
});
