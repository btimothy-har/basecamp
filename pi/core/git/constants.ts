import * as os from "node:os";
import * as path from "node:path";
import { getBasecampEnv } from "../host/env.ts";

// Resolved at use-time (never captured at import) so tests can redirect it via
// BASECAMP_WORKTREES_ROOT; defaults to ~/.worktrees.
export function worktreesRoot(): string {
	return getBasecampEnv("BASECAMP_WORKTREES_ROOT") ?? path.join(os.homedir(), ".worktrees");
}
export const WORKTREE_BRANCH_PREFIX = "wt/";
// Deliverable agent runs mint branches in this namespace (`agent/<handle>`); the legacy
// per-run namespace was `agent-<token>/<name>`. The sweep recognizes both.
export const AGENT_BRANCH_NAMESPACE = "agent/";
export const WORKTREE_LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
