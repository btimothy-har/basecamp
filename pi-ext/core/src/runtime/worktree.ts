import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { createLocalBashOperations, isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { getSessionEffectiveCwd, isPathWithin, type SessionState } from "../../../platform/config.ts";

export {
	attachWorktreeDir,
	branchName,
	ensureWorktreeLabel,
	findWorktreeRecord,
	getOrCreateWorktree,
	gitWorktreeRecords,
	labelFromWorktreePath,
	listWorktrees,
	parseWorktreeList,
	validateProtectedCheckout,
	validateWorktreePath,
	type WorktreeResult,
	type WorktreeSummary,
} from "../../../workspace/src/worktree";

// ---------------------------------------------------------------------------
// Tool guards
// ---------------------------------------------------------------------------

/** Expand ~ in path (mirrors pi's path-utils expandPath). */
function expandPath(filePath: string): string {
	const normalized = filePath.startsWith("@") ? filePath.slice(1) : filePath;
	if (normalized === "~") return os.homedir();
	if (normalized.startsWith("~/")) return os.homedir() + normalized.slice(1);
	return normalized;
}

/** Shell-quote a string for safe embedding in bash commands. */
function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

function isAdditionalPath(state: SessionState, resolved: string): boolean {
	return state.additionalDirs.some((dir: string) => isPathWithin(resolved, dir));
}

const STRUCTURED_PATH_TOOLS = new Set(["read", "edit", "write", "grep", "find", "ls"]);
const STRUCTURED_MUTATION_TOOLS = new Set(["edit", "write"]);
const OPTIONAL_PATH_TOOLS = new Set(["grep", "find", "ls"]);

/**
 * Register tool_call guards for protected checkout and worktree enforcement.
 */
export function registerWorktreeGuards(pi: ExtensionAPI, getState: () => SessionState): void {
	// user_bash fires when the user types !cmd directly in pi's terminal.
	// Override operations so shell commands run from Basecamp's effective cwd.
	pi.on("user_bash", async () => {
		const state = getState();
		if (!state.worktreeDir) return;

		const effectiveCwd = getSessionEffectiveCwd(state);
		const local = createLocalBashOperations();
		return {
			operations: {
				exec: (command: string, _cwd: string, options) => local.exec(command, effectiveCwd, options),
			},
		};
	});

	pi.on("tool_call", async (event) => {
		const state = getState();
		const protectedCheckout = state.repoRoot;
		const worktreeDir = state.worktreeDir;
		const effectiveCwd = getSessionEffectiveCwd(state);

		if (isToolCallEventType("bash", event)) {
			if (!worktreeDir) return;
			const cmd = event.input.command;
			const quoted = shellQuote(effectiveCwd);
			const alreadyCd = cmd?.startsWith(`cd ${effectiveCwd}`) || cmd?.startsWith(`cd ${quoted}`);
			if (cmd && !alreadyCd) {
				event.input.command = `cd ${quoted} && ${cmd}`;
			}
			return;
		}

		if (!STRUCTURED_PATH_TOOLS.has(event.toolName)) return;

		const input = event.input as { path?: string };
		if (worktreeDir && OPTIONAL_PATH_TOOLS.has(event.toolName) && !input.path) {
			input.path = effectiveCwd;
			return;
		}
		if (!input.path) return;

		const expanded = expandPath(input.path);
		const isAbsolute = path.isAbsolute(expanded);
		const resolved = isAbsolute ? path.resolve(expanded) : path.resolve(effectiveCwd, expanded);
		const isStructuredMutation = STRUCTURED_MUTATION_TOOLS.has(event.toolName);
		const isProtectedPath = isPathWithin(resolved, protectedCheckout);

		if (!worktreeDir && isStructuredMutation && isProtectedPath) {
			if (state.unsafeEdit) return;
			return {
				block: true,
				reason:
					`Path "${input.path}" resolves to the protected checkout (${protectedCheckout}). ` +
					"Activate an execution worktree before editing project files.",
			};
		}

		if (worktreeDir && isStructuredMutation && isProtectedPath) {
			// Relative paths are retargeted to the worktree; use absolute paths for intentional protected checkout edits.
			if (state.unsafeEdit && isAbsolute) return;
			return {
				block: true,
				reason:
					`Path "${input.path}" resolves to the protected checkout (${protectedCheckout}). ` +
					`Use the active worktree instead: ${worktreeDir}`,
			};
		}

		if (isAdditionalPath(state, resolved)) return;

		if (!worktreeDir) return;

		if (!isAbsolute && !isPathWithin(resolved, worktreeDir)) {
			return {
				block: true,
				reason: `Relative path "${input.path}" escapes the active worktree (${worktreeDir}).`,
			};
		}

		if (isProtectedPath) {
			return {
				block: true,
				reason:
					`Path "${input.path}" resolves to the protected checkout (${protectedCheckout}). ` +
					`Use the active worktree instead: ${worktreeDir}`,
			};
		}

		if (!isAbsolute) {
			input.path = resolved;
		}
	});
}
