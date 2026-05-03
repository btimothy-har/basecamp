import * as os from "node:os";
import * as path from "node:path";

export const WORKTREES_ROOT = path.join(os.homedir(), ".worktrees");
export const WORKTREE_BRANCH_PREFIX = "wt/";
export const WORKTREE_LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
export const SCRATCH_ROOT = "/tmp/pi";
