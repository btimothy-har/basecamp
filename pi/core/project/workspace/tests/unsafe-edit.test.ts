import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { UnsafeEditConstraints, WorkspaceState } from "../state.ts";
import { applyUnsafeEditFlag } from "../unsafe-edit.ts";

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

function constraints(overrides: Partial<UnsafeEditConstraints> = {}): UnsafeEditConstraints {
	return {
		readOnly: false,
		hasUI: true,
		isSubagent: false,
		sandboxed: false,
		...overrides,
	};
}

describe("unsafe-edit flag state", () => {
	it("stays disabled when the flag is absent", () => {
		const state = baseWorkspaceState({ unsafeEdit: true });
		const result = applyUnsafeEditFlag(state, false, constraints({ sandboxed: true }));

		assert.equal(result, "disabled");
		assert.equal(state.unsafeEdit, false);
	});

	it("enables unsafe edit when requested", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, constraints());

		assert.equal(result, "enabled");
		assert.equal(state.unsafeEdit, true);
	});

	it("ignores unsafe edit when read-only is active", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, constraints({ readOnly: true, sandboxed: true }));

		assert.equal(result, "ignored-read-only");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit in ordinary subagent sessions", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, constraints({ isSubagent: true }));

		assert.equal(result, "ignored-subagent");
		assert.equal(state.unsafeEdit, false);
	});

	it("ignores unsafe edit without an interactive UI", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, constraints({ hasUI: false }));

		assert.equal(result, "ignored-non-interactive");
		assert.equal(state.unsafeEdit, false);
	});

	it("enables unsafe edit for an explicitly sandboxed headless subagent", () => {
		const state = baseWorkspaceState();
		const result = applyUnsafeEditFlag(state, true, constraints({ hasUI: false, isSubagent: true, sandboxed: true }));

		assert.equal(result, "enabled");
		assert.equal(state.unsafeEdit, true);
	});
});
