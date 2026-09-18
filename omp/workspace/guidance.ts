import type {
	BeforeAgentStartEvent,
	BeforeAgentStartEventResult,
	ExtensionAPI,
	ExtensionContext,
} from "@oh-my-pi/pi-coding-agent";
import { vcsGitDiscover } from "@oh-my-pi/pi-natives";

export const WORKSPACE_GUIDANCE = `<workspace-policy>
The canonical checkout is for inspection and planning only. A detached worktree is writable but temporary, and implementation may proceed there. If its changes should survive the session, ask the user to run \`/wt <branch>\` before exit so OMP carries the session and changes into a branch-backed worktree. A branch-backed worktree is durable. Approval does not switch workspaces. Do not create or switch branches to bypass the user handoff. Treat pre-existing changes as user work. If you cannot interact with the user, report the required handoff to the primary session.
</workspace-policy>`;

function isGitWorkspace(cwd: string): boolean {
	try {
		return vcsGitDiscover(cwd) !== null;
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
