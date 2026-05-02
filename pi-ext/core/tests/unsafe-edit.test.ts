import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { SessionState } from "../../platform/config.ts";
import { applyUnsafeEditFlag } from "../src/runtime/unsafe-edit.ts";

function baseSessionState(overrides: Partial<SessionState> = {}): SessionState {
	return {
		projectName: "test-project",
		project: null,
		launchCwd: "/repo",
		repoRoot: "/repo",
		additionalDirs: [],
		repoName: "repo",
		isRepo: true,
		remoteUrl: "git@github.com:test/repo.git",
		scratchDir: "/tmp/pi/repo",
		workingStyle: "engineering",
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent: null,
		projectWarnings: [],
		unsafeEdit: false,
		...overrides,
	};
}

describe("unsafe-edit flag state", () => {
	it("stays disabled when the flag is absent", () => {
		const state = baseSessionState({ unsafeEdit: true });
		const result = applyUnsafeEditFlag(state, false, { readOnly: false, hasUI: true, isSubagent: false });

		assert.equal(result, "disabled");
		assert.equal(state.unsafeEdit, false);
	});

	it("enables unsafe edit when requested", () => {
		const state = baseSessionState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: true, isSubagent: false });

		assert.equal(result, "enabled");
		assert.equal(state.unsafeEdit, true);
	});

	it("ignores unsafe edit when read-only is active", () => {
		const state = baseSessionState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: true, hasUI: true, isSubagent: false });

		assert.equal(result, "ignored-read-only");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit in subagent sessions", () => {
		const state = baseSessionState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: true, isSubagent: true });

		assert.equal(result, "ignored-subagent");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit without an interactive UI", () => {
		const state = baseSessionState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: false, isSubagent: false });

		assert.equal(result, "ignored-non-interactive");
		assert.equal(state.unsafeEdit, false);
	});
});
