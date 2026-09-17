import type {
	BeforeAgentStartEvent,
	BeforeAgentStartEventResult,
	ExtensionAPI,
	ExtensionContext,
} from "@oh-my-pi/pi-coding-agent";
import type { WorkspaceEnvironment } from "./environment.ts";
import { normalizeRoot } from "./paths.ts";
import type { RepositoryCache, RepositoryIdentity } from "./repository.ts";

export interface WorkspaceGuidanceDeps {
	env: WorkspaceEnvironment;
	repos: RepositoryCache;
}

export function describeWorkspace(identity: RepositoryIdentity, env: WorkspaceEnvironment): string {
	const root = normalizeRoot(identity.root);
	const primaryRoot = normalizeRoot(identity.primaryRoot);
	if (root === primaryRoot) {
		return `<workspace-policy>\nYou are in the repository's canonical checkout at ${root}. Treat it as read-only: inspect, coordinate, and plan here, but do not implement or mutate repository files. Before implementation, ask the user to run \`/wt <branch>\`. Approval does not change workspaces; proceed with mutations only after the live cwd is a linked worktree.\n</workspace-policy>`;
	}

	const scratchRoot = env.scratchRoot ? normalizeRoot(env.scratchRoot) : null;
	if (scratchRoot === root) {
		const inherited = env.inheritedWip ? " It includes uncommitted work copied from the canonical checkout." : "";
		return `<workspace-policy>\nYou are in a temporary Basecamp scratch worktree at ${root}.${inherited} Repository mutations are allowed here, but this scratch is removed when unchanged and is not the durable home for implementation. Before the session exits, ask the user to run \`/wt <branch>\` so OMP carries the session and changes into a branch-backed worktree. Approval does not perform that handoff.\n</workspace-policy>`;
	}

	if (identity.branch) {
		return `<workspace-policy>\nYou are in the durable branch worktree at ${root} on branch ${identity.branch}. Repository implementation may proceed here.\n</workspace-policy>`;
	}

	return `<workspace-policy>\nYou are in a detached worktree at ${root}. Repository mutations are allowed here, but detached work may be discarded when this session exits. Before relying on changes as durable, ask the user to run \`/wt <branch>\`. Approval does not perform that handoff.\n</workspace-policy>`;
}

export function injectWorkspaceGuidance(
	event: BeforeAgentStartEvent,
	ctx: ExtensionContext,
	deps: WorkspaceGuidanceDeps,
): BeforeAgentStartEventResult | undefined {
	const identity = deps.repos.identify(ctx.cwd);
	if (!identity) return undefined;
	return { systemPrompt: [...event.systemPrompt, describeWorkspace(identity, deps.env)] };
}

export default function registerWorkspaceGuidance(pi: ExtensionAPI, deps: WorkspaceGuidanceDeps): void {
	pi.on("before_agent_start", (event, ctx) => injectWorkspaceGuidance(event, ctx, deps));
}
