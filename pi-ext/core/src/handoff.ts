/**
 * Handoff — compact the current session with a structured summary,
 * then continue in a new session with that summary as context.
 *
 * Usage:
 *   /handoff                          — compact with full summary, start fresh
 *   /handoff focus on the auth module — compact focused on auth, start fresh
 *
 * Args (if any) are appended to the compaction instructions to focus the
 * summary. The new session receives the focused summary as its context.
 *
 * This replaces the old Python handoff that spawned a subprocess to
 * summarize, wrote launcher scripts, and opened a new terminal pane.
 * Pi's built-in compaction + newSession does the same thing natively.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getPiCommand } from "../../config.ts";

const HANDOFF_INSTRUCTIONS = `\
Summarize this conversation for handoff to a new session. The new session \
will continue the work with only this summary as context — no conversation \
history carries over. Be specific: include file paths, function names, and \
concrete details.

Structure your summary with the following sections:

## Narrative

What was the user working on? What was the goal? How far along are we? \
Write this as a brief story of the session — the arc from start to current \
state. Include the collaborative dynamic: what the user drove vs what you \
proposed.

## Work State

Concrete details of what changed:
- Files created, modified, or deleted
- Commits made (hashes and messages)
- Current branch and uncommitted changes
- What's done vs what's still in progress

## Decisions & Rationale

Key decisions made during the session and *why* they were made. Include:
- Approaches chosen and the reasoning behind them
- Alternatives that were considered and rejected (and why)
- Trade-offs that were explicitly accepted

## Discovered Context

Things that took effort to find or surface — context the new session \
shouldn't have to rediscover:
- File paths, modules, patterns, and architecture details
- Constraints or opinions the user expressed
- Non-obvious relationships between components
- Gotchas or caveats encountered

## Open Threads

What needs to happen next:
- Immediate next steps, in priority order
- Unresolved questions or decisions deferred for later
- Ideas flagged but not yet acted on`;

export function registerHandoff(pi: ExtensionAPI) {
	pi.registerCommand("handoff", {
		description: "Summarize session via a forked agent, then start a new session with the summary",
		handler: async (args, ctx) => {
			await ctx.waitForIdle();

			const sessionFile = ctx.sessionManager.getSessionFile();
			if (!sessionFile) {
				ctx.ui.notify("Cannot handoff an ephemeral session", "error");
				return;
			}

			const focus = args?.trim();
			const instructions = focus ? `${HANDOFF_INSTRUCTIONS}\n\nFocus the summary on: ${focus}` : HANDOFF_INSTRUCTIONS;

			ctx.ui.notify("Generating handoff summary...", "info");

			// Fork the current session into a separate pi process to
			// generate the summary. The forked agent sees the full
			// conversation context but doesn't modify the current session.
			const [piCmd, ...piPrefix] = getPiCommand();
			const result = await pi.exec(
				piCmd,
				[...piPrefix, "-p", "--fork", sessionFile, "--no-session", "--", instructions],
				{
					timeout: 180_000,
				},
			);

			if (result.code !== 0) {
				ctx.ui.notify(`Handoff failed: ${result.stderr || "summarization error"}`, "error");
				return;
			}

			const summary = result.stdout.trim();
			if (!summary) {
				ctx.ui.notify("Handoff failed: empty summary", "error");
				return;
			}

			ctx.ui.notify("Starting new session...", "info");

			await ctx.newSession({
				parentSession: sessionFile,
				setup: async (sm) => {
					sm.appendMessage({
						role: "user",
						content: [
							{
								type: "text",
								text:
									"This session is a continuation from a prior session. " +
									"Here is a summary of what happened before:\n\n" +
									`<handoff-context>\n${summary}\n</handoff-context>\n\n` +
									"Wait for my next instruction before proceeding.",
							},
						],
						timestamp: Date.now(),
					});
				},
			});
		},
	});
}
