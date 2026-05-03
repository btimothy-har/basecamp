import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceState } from "../../platform/workspace.ts";
import { applyUnsafeEditFlag } from "../../workspace/src/unsafe-edit.ts";

function baseWorkspaceState(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: "/repo",
		scratchDir: "/tmp/pi/repo",
		repo: {
			isRepo: true,
			name: "repo",
			root: "/repo",
			remoteUrl: "git@github.com:test/repo.git",
		},
		protectedRoot: "/repo",
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

describe("unsafe-edit flag state", () => {
	it("stays disabled when the flag is absent", () => {
		const state = baseWorkspaceState({ unsafeEdit: true });
		const result = applyUnsafeEditFlag(state, false, { readOnly: false, hasUI: true, isSubagent: false });

		assert.equal(result, "disabled");
		assert.equal(state.unsafeEdit, false);
	});

	it("enables unsafe edit when requested", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: true, isSubagent: false });

		assert.equal(result, "enabled");
		assert.equal(state.unsafeEdit, true);
	});

	it("ignores unsafe edit when read-only is active", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: true, hasUI: true, isSubagent: false });

		assert.equal(result, "ignored-read-only");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit in subagent sessions", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: true, isSubagent: true });

		assert.equal(result, "ignored-subagent");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit without an interactive UI", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, { readOnly: false, hasUI: false, isSubagent: false });

		assert.equal(result, "ignored-non-interactive");
		assert.equal(state.unsafeEdit, false);
	});
});
