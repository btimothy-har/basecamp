import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	ALLOWED_ROOT,
	activeWorktreeState,
	baseWorkspaceState,
	createGuards,
	REPO_ROOT,
	runGuard,
	runToolCallGuard,
	WORKTREE_DIR,
} from "./guards-harness.ts";

describe("worktree guards bash cwd", () => {
	it("prefixes bash tool calls with the effective cwd when a worktree is active", async () => {
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command: "pwd" });

		assert.equal(result, undefined);
		assert.equal(event.input.command, `cd '${WORKTREE_DIR}' && pwd`);
	});

	it("leaves bash tool calls unchanged when no worktree is active", async () => {
		const { event, result } = await runToolCallGuard(baseWorkspaceState(), "bash", { command: "pwd" });

		assert.equal(result, undefined);
		assert.equal(event.input.command, "pwd");
	});

	it("does not double-prefix unquoted cd commands", async () => {
		const command = `cd ${WORKTREE_DIR} && pwd`;
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command });

		assert.equal(result, undefined);
		assert.equal(event.input.command, command);
	});

	it("does not double-prefix quoted cd commands", async () => {
		const command = `cd '${WORKTREE_DIR}' && pwd`;
		const { event, result } = await runToolCallGuard(activeWorktreeState(), "bash", { command });

		assert.equal(result, undefined);
		assert.equal(event.input.command, command);
	});

	it("shell-quotes effective cwd paths with spaces and single quotes", async () => {
		const effectiveCwd = "/tmp/pi/work tree/it's feature";
		const { event, result } = await runToolCallGuard(
			activeWorktreeState({
				effectiveCwd,
				activeWorktree: {
					kind: "git-worktree",
					label: "it's feature",
					path: effectiveCwd,
					branch: "bh/its-feature",
					created: false,
				},
			}),
			"bash",
			{ command: "pwd" },
		);

		assert.equal(result, undefined);
		assert.equal(event.input.command, "cd '/tmp/pi/work tree/it'\\''s feature' && pwd");
	});
});

describe("worktree guards optional path cwd", () => {
	for (const toolName of ["grep", "find", "ls"]) {
		it(`sets omitted ${toolName} path to effective cwd when a worktree is active`, async () => {
			const { event, result } = await runToolCallGuard(activeWorktreeState(), toolName, {});

			assert.equal(result, undefined);
			assert.equal(event.input.path, WORKTREE_DIR);
		});

		it(`does not set omitted ${toolName} path when no worktree is active`, async () => {
			const { event, result } = await runToolCallGuard(baseWorkspaceState(), toolName, {});

			assert.equal(result, undefined);
			assert.equal(event.input.path, undefined);
			assert.equal("path" in event.input, false);
		});

		it(`does not overwrite an existing ${toolName} path with effective cwd`, async () => {
			const inputPath = path.join(WORKTREE_DIR, "src");
			const { event, result } = await runToolCallGuard(activeWorktreeState(), toolName, { path: inputPath });

			assert.equal(result, undefined);
			assert.equal(event.input.path, inputPath);
		});
	}
});

describe("worktree guards user bash cwd", () => {
	it("executes user bash commands from the effective cwd", async () => {
		const tempRoot = await fs.mkdtemp(path.join(await fs.realpath(os.tmpdir()), "basecamp-guards-"));
		try {
			const repoRoot = path.join(tempRoot, "repo");
			const effectiveCwd = path.join(tempRoot, "worktree");
			await fs.mkdir(repoRoot);
			await fs.mkdir(effectiveCwd);

			const { userBash } = createGuards(
				activeWorktreeState({
					launchCwd: repoRoot,
					effectiveCwd,
					protectedRoot: repoRoot,
					repo: {
						isRepo: true,
						name: "repo",
						root: repoRoot,
						remoteUrl: "git@github.com:test/repo.git",
					},
					activeWorktree: {
						kind: "git-worktree",
						label: "feature",
						path: effectiveCwd,
						branch: "bh/feature",
						created: false,
					},
				}),
			);
			const result = await userBash({ type: "user_bash", command: "pwd", excludeFromContext: false, cwd: repoRoot });

			assert.ok(result?.operations, "user_bash should return bash operations for an active worktree");

			let output = "";
			const execResult = await result.operations.exec("pwd", repoRoot, {
				onData: (data) => {
					output += data.toString();
				},
				timeout: 5_000,
			});

			assert.equal(execResult.exitCode, 0);
			assert.equal(output.trim(), effectiveCwd);
		} finally {
			await fs.rm(tempRoot, { recursive: true, force: true });
		}
	});
});

describe("worktree guards unsafe-edit", () => {
	it("blocks protected checkout edit by default without worktree", async () => {
		const { result } = await runGuard(baseWorkspaceState(), "edit", "file.ts");

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("allows protected checkout edit without worktree when unsafe-edit is active", async () => {
		const { result } = await runGuard(baseWorkspaceState({ unsafeEdit: true }), "edit", "file.ts");

		assert.equal(result, undefined);
	});

	it("allows absolute protected checkout edit with active worktree when unsafe-edit is active", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"write",
			path.join(REPO_ROOT, "file.ts"),
		);

		assert.equal(result, undefined);
	});

	it("blocks relative protected checkout edits with active worktree", async () => {
		const relativeProtectedPath = path.relative(WORKTREE_DIR, path.join(REPO_ROOT, "file.ts"));
		const { result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", relativeProtectedPath);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("still blocks relative paths that escape the active worktree", async () => {
		const { result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", "../outside.ts");

		assert.equal(result?.block, true);
		// A relative mutation that escapes the worktree resolves outside the write scope, so the
		// allowed_dirs confinement now catches it (a superset of the old relative-escape check).
		assert.match(result.reason ?? "", /outside your writable scope/);
	});

	it("allows paths under allowed roots to bypass active worktree confinement", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"edit",
			path.join(ALLOWED_ROOT, "outside.ts"),
			[ALLOWED_ROOT],
		);

		assert.equal(result, undefined);
	});

	it("does not allow allowed roots to bypass protected checkout checks", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"read",
			path.join(REPO_ROOT, "file.ts"),
			[REPO_ROOT],
		);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("does not allow read tools to target protected checkout with active worktree", async () => {
		const { result } = await runGuard(
			activeWorktreeState({ unsafeEdit: true }),
			"read",
			path.join(REPO_ROOT, "file.ts"),
		);

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /protected checkout/);
	});

	it("continues to retarget relative worktree edits", async () => {
		const { event, result } = await runGuard(activeWorktreeState({ unsafeEdit: true }), "edit", "src/file.ts");

		assert.equal(result, undefined);
		assert.equal(event.input.path, path.join(WORKTREE_DIR, "src/file.ts"));
	});
});

describe("worktree guards write-scope confinement (allowed_dirs)", () => {
	const SIBLING_WORKTREE = "/worktrees/repo/other-agent";

	it("blocks an absolute mutation into a sibling worktree outside the write scope", async () => {
		const { result } = await runGuard(activeWorktreeState(), "write", path.join(SIBLING_WORKTREE, "f.ts"));

		assert.equal(result?.block, true);
		assert.match(result.reason ?? "", /outside your writable scope/);
	});

	it("allows a mutation inside the active worktree", async () => {
		const { result } = await runGuard(activeWorktreeState(), "write", path.join(WORKTREE_DIR, "src/f.ts"));

		assert.equal(result, undefined);
	});

	it("allows a mutation inside the scratch dir", async () => {
		const { result } = await runGuard(activeWorktreeState(), "write", "/tmp/pi/repo/note.md");

		assert.equal(result, undefined);
	});

	it("does not confine read tools to the write scope", async () => {
		const { result } = await runGuard(activeWorktreeState(), "read", path.join(SIBLING_WORKTREE, "f.ts"));

		assert.equal(result, undefined);
	});
});
