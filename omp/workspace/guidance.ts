import type {
	BeforeAgentStartEvent,
	BeforeAgentStartEventResult,
	ExtensionAPI,
	ExtensionContext,
} from "@oh-my-pi/pi-coding-agent";
import { vcsGitRepoInfo } from "@oh-my-pi/pi-natives";

export const WORKSPACE_GUIDANCE = `<workspace-policy>
The primary worktree must never be modified. A detached HEAD may be used for throwaway edits. Durable modifications must be made in a branch-backed worktree. Use Git tools to inspect the current checkout. If durable modifications are needed from any other checkout, ask the user to create a durable worktree with \`/wt <branch>\` and wait for them to do so. Do not create or switch branches yourself to bypass this handoff. Treat pre-existing changes as user work.
</workspace-policy>`;

function isGitWorkspace(cwd: string): boolean {
	try {
		return vcsGitRepoInfo(cwd) !== null;
	} catch {
		return false;
	}
}

export function injectWorkspaceGuidance(
	event: BeforeAgentStartEvent,
	ctx: ExtensionContext,
): BeforeAgentStartEventResult | undefined {
	if (!isGitWorkspace(ctx.cwd)) return undefined;
	return { systemPrompt: [...event.systemPrompt, WORKSPACE_GUIDANCE] };
}

export default function registerWorkspaceGuidance(pi: ExtensionAPI): void {
	pi.on("before_agent_start", injectWorkspaceGuidance);
}
