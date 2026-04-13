/**
 * Git Protect Extension for pi
 *
 * Guards against destructive git and gh operations:
 * - DENY: git push --force, --force-with-lease, -f
 * - DENY: git push --delete or colon-prefix ref deletion
 * - DENY: git clean -f / --force
 * - DENY: destructive gh commands (allow only read-only + gh issue)
 * - ALLOW: mkdir when all target directories already exist
 *
 * Ported from bc-git-protect (Claude Code plugin).
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { statSync } from "node:fs";

// ---------------------------------------------------------------------------
// git push guards
// ---------------------------------------------------------------------------

function isForcePush(cmd: string): string | null {
	if (!/^git\s+push\b/.test(cmd)) return null;

	if (/\s(--force|--force-with-lease)(\s|$)/.test(cmd) || /\s-[a-zA-Z]*f/.test(cmd)) {
		return "Force push is blocked — protects remote history.";
	}

	return null;
}

function isRemoteRefDelete(cmd: string): string | null {
	if (!/^git\s+push\b/.test(cmd)) return null;

	if (/\s--delete(\s|$)/.test(cmd) || /\s:[^\s]/.test(cmd)) {
		return "Deleting remote refs is blocked.";
	}

	return null;
}

// ---------------------------------------------------------------------------
// git clean guard
// ---------------------------------------------------------------------------

function isForceClean(cmd: string): string | null {
	if (!/^git\s+clean\b/.test(cmd)) return null;

	if (/\s-[a-zA-Z]*f/.test(cmd) || /\s--force/.test(cmd)) {
		return "git clean -f permanently deletes untracked files — not recoverable.";
	}

	return null;
}

// ---------------------------------------------------------------------------
// gh command guard
// ---------------------------------------------------------------------------

function getGhBlockReason(cmd: string): string | null {
	if (!/^gh\s+/.test(cmd)) return null;

	// Allow all gh issue operations
	if (/^gh\s+issue(\s|$)/.test(cmd)) return null;

	// Allow read-only operations
	if (
		/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/.test(cmd) ||
		/^gh\s+repo\s+(view|list|clone|set-default)(\s|$)/.test(cmd) ||
		/^gh\s+run\s+watch(\s|$)/.test(cmd) ||
		/^gh\s+search\s/.test(cmd) ||
		/^gh\s+browse(\s|$)/.test(cmd)
	) {
		return null;
	}

	return "Destructive gh command blocked. Run from terminal if needed.";
}

// ---------------------------------------------------------------------------
// mkdir auto-approve (idempotent no-op)
// ---------------------------------------------------------------------------

function isIdempotentMkdir(cmd: string): boolean {
	// Only simple mkdir commands — no chaining, substitution, or redirects
	if (!/^mkdir\s/.test(cmd)) return false;
	if (/[\n\r]/.test(cmd)) return false;
	if (/[;|&`$()<>]/.test(cmd)) return false;

	// Split into words, extract paths (skip flags)
	const args = cmd.split(/\s+/).slice(1);
	const paths: string[] = [];
	for (const arg of args) {
		if (arg.startsWith("-")) continue;
		paths.push(arg);
	}

	if (paths.length === 0) return false;

	// All paths must already exist
	return paths.every((p) => {
		const expanded = p.startsWith("~/") ? `${process.env.HOME}/${p.slice(2)}` : p;
		try {
			return statSync(expanded).isDirectory();
		} catch {
			return false;
		}
	});
}

// ---------------------------------------------------------------------------
// Check a bash command and return a block reason if it should be blocked
// ---------------------------------------------------------------------------

function checkCommand(cmd: string): string | null {
	// --- git guards ---
	const forcePushReason = isForcePush(cmd);
	if (forcePushReason) return forcePushReason;

	const refDeleteReason = isRemoteRefDelete(cmd);
	if (refDeleteReason) return refDeleteReason;

	const cleanReason = isForceClean(cmd);
	if (cleanReason) return cleanReason;

	// --- gh guard ---
	const ghReason = getGhBlockReason(cmd);
	if (ghReason) return ghReason;

	return null;
}

// ---------------------------------------------------------------------------
// Main extension
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return;

		const cmd = event.input.command;
		if (!cmd) return;

		const reason = checkCommand(cmd);
		if (reason) {
			return { block: true, reason };
		}
	});
}
