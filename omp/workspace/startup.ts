/**
 * Canonical-checkout startup warning. Fires once per entry into a canonical
 * checkout (session start or switch) in a primary TUI session only.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { vcsGitDiscover } from "@oh-my-pi/pi-natives";

function normalizeRoot(root: string): string {
	try {
		return fs.realpathSync(root);
	} catch {
		return path.resolve(root);
	}
}

export function canonicalCheckoutRoot(ctx: ExtensionContext): string | null {
	try {
		const repo = vcsGitDiscover(ctx.cwd);
		if (!repo) return null;
		const root = normalizeRoot(repo.info().repoRoot);
		return root === normalizeRoot(repo.primaryRoot()) ? root : null;
	} catch {
		return null;
	}
}

export default function registerStartupWarning(pi: ExtensionAPI): void {
	let warnedRoot: string | null = null;
	const check = (ctx: ExtensionContext): void => {
		if (ctx.mode !== "tui") return;
		const root = canonicalCheckoutRoot(ctx);
		if (!root) {
			warnedRoot = null;
			return;
		}
		if (warnedRoot === root) return;
		warnedRoot = root;
		ctx.ui.notify(
			`Running in the canonical checkout (${root}). Use /wt <branch> before repository implementation.`,
			"warning",
		);
	};
	pi.on("session_start", (_event, ctx) => check(ctx));
	pi.on("session_switch", (_event, ctx) => check(ctx));
}
