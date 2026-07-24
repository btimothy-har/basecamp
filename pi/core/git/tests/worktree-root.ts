import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

/**
 * Redirect `worktreesRoot()` to a throwaway temp dir for this test process via
 * BASECAMP_WORKTREES_ROOT, so worktree tests never write under the real ~/.worktrees.
 *
 * Call as the first statement of a test module (before any module-level path constant
 * derived from `worktreesRoot()`); the Node test runner isolates each test file in its own
 * process, so the env override and its exit-time cleanup are scoped to that file.
 */
export function useTempWorktreesRoot(): string {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-wt-root-"));
	process.env.BASECAMP_WORKTREES_ROOT = root;
	process.on("exit", () => fs.rmSync(root, { recursive: true, force: true }));
	return root;
}
