/**
 * Session Lifecycle & Project Context
 *
 * session_start:
 *   - Determines git repo name (GIT_REPO env var)
 *   - Creates scratch directories for PR workflows
 *   - Sets up inbox directory keyed by session ID
 *
 * before_agent_start:
 *   - Appends project context from BASECAMP_CONTEXT_FILE to system prompt
 *
 * Ported from:
 *   - plugins/pi-eng/extension/index.ts (session_start handler)
 *   - plugins/companion/scripts/session-init.sh (session ID / inbox)
 *   - plugins/companion/scripts/project-context.sh (context injection)
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs/promises";
import * as path from "node:path";

export function registerLifecycle(pi: ExtensionAPI): void {
	// Context file content cached at session_start, appended to system prompt
	// each turn via before_agent_start (same pattern as pi's AGENTS.md handling).
	let contextContent: string | undefined;

	pi.on("session_start", async (_event, ctx) => {
		// 1. Determine git repo name
		let gitRepo: string;
		try {
			const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd: ctx.cwd });
			gitRepo = path.basename(result.stdout.trim());
		} catch {
			gitRepo = path.basename(ctx.cwd);
		}
		process.env.GIT_REPO = gitRepo;

		// 2. Create scratch directories
		const scratch = process.env.BASECAMP_SCRATCH_DIR || `/tmp/claude-workspace/${gitRepo}`;
		await fs.mkdir(path.join(scratch, "pull_requests"), { recursive: true });
		await fs.mkdir(path.join(scratch, "pr-comments"), { recursive: true });

		// 3. Set up inbox directory keyed by session
		const sessionFile = ctx.sessionManager.getSessionFile();
		if (sessionFile) {
			const sessionId = path.basename(sessionFile, path.extname(sessionFile));
			const inboxDir = `/tmp/claude-workspace/inbox/${sessionId}`;
			await fs.mkdir(inboxDir, { recursive: true });
			process.env.BASECAMP_INBOX_DIR = inboxDir;
		}

		// 4. Cache context file content
		const contextFile = process.env.BASECAMP_CONTEXT_FILE;
		if (contextFile) {
			try {
				contextContent = await fs.readFile(contextFile, "utf8");
			} catch {
				contextContent = undefined;
			}
		} else {
			contextContent = undefined;
		}

		ctx.ui.notify(`basecamp: repo=${gitRepo}`, "info");
	});

	pi.on("before_agent_start", async (event, _ctx) => {
		if (!contextContent) return;

		return {
			systemPrompt: event.systemPrompt + `\n\n# Basecamp Project Context\n\n${contextContent}`,
		};
	});
}
