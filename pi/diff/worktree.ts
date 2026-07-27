/**
 * The directory a review is keyed on.
 *
 * One resolver for the whole domain: the sidecar path is a hash of this
 * string, so if the tool that writes it and the command that reads it
 * disagreed by even a normalized path separator, agent rationale would be
 * written somewhere `/diff` never looks and neither side would report it.
 */

import { getBasecampEnv } from "#core/host/env.ts";
import { getWorkspaceEffectiveCwd } from "#core/project/workspace/state.ts";

export function reviewWorktreeDir(): string {
	return getBasecampEnv("BASECAMP_WORKTREE_DIR") ?? getWorkspaceEffectiveCwd();
}
