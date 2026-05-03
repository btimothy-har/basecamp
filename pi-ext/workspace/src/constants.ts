import * as os from "node:os";
import * as path from "node:path";

export const WORKTREES_ROOT = path.join(os.homedir(), ".worktrees");
export const WORKTREE_BRANCH_PREFIX = "wt/";
export const SCRATCH_ROOT = "/tmp/pi";
export const WORKSPACE_AFFINITY_ENTRY = "workspace.execution-target-affinity";
