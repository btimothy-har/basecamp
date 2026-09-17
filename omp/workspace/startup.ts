/**
 * Canonical-checkout startup warning. Fires once per entry into a canonical
 * checkout (session start or switch) in a primary TUI session only: task
 * agents and headless modes never notify, linked/detached worktrees and
 * non-Git directories are not canonical, and ordinary turns stay quiet.
 */
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { normalizeRoot } from "./paths.ts";
import type { RepositoryCache } from "./repository.ts";

/**
 * The canonical checkout root containing the live cwd, or null when cwd is
 * outside Git or sits in a linked/detached worktree. Identity — real Git
 * top-level equal to the real primary root — is what matters, not the branch
 * name: canonical on a feature branch still counts.
 */
export function canonicalCheckoutRoot(ctx: ExtensionContext, repos: RepositoryCache): string | null {
	const identity = repos.identify(ctx.cwd);
	if (!identity) return null;
	const root = normalizeRoot(identity.root);
	return root === normalizeRoot(identity.primaryRoot) ? root : null;
}

export default function registerStartupWarning(pi: ExtensionAPI, repos: RepositoryCache): void {
	let warnedRoot: string | null = null;
	const check = (ctx: ExtensionContext): void => {
		if (ctx.mode !== "tui") return;
		const root = canonicalCheckoutRoot(ctx, repos);
		if (!root) {
			// Left canonical; re-entering through a later switch warns again.
			warnedRoot = null;
			return;
		}
		if (warnedRoot === root) return;
		warnedRoot = root;
		ctx.ui.notify(
			`Basecamp: Running in the canonical checkout (${root}). Structured repository edits are blocked; run /wt <branch> before implementation.`,
			"warning",
		);
	};
	pi.on("session_start", (_event, ctx) => check(ctx));
	pi.on("session_switch", (_event, ctx) => check(ctx));
}
