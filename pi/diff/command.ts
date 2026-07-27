/** `/diff` — review this branch's changes in hunk and bring the annotations back. */

import * as fs from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { resolveReviewBase } from "#core/git/repo.ts";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { checkHerdrEligibility, closeHerdrTab, openHerdrTab, runInHerdrPane } from "#core/ui/herdr-pane.ts";
import { formatAnnotations } from "./annotations.ts";
import { detectHunk, getHunkSession, readUserNotes, type UserNote } from "./hunk.ts";
import { forgetTab, rememberTab } from "./session-state.ts";
import { sidecarPath } from "./sidecar.ts";

// hunk's own update nag would render inside a tab Basecamp owns.
const HUNK_TAB_ENV = { HUNK_DISABLE_UPDATE_NOTICE: "1" };

function worktreeDirFor(ctx: ExtensionContext): string {
	return getBasecampEnv("BASECAMP_WORKTREE_DIR") ?? ctx.cwd;
}

function tabLabel(worktreeDir: string): string {
	return `diff: ${getBasecampEnv("BASECAMP_WORKTREE_LABEL") ?? worktreeDir.split("/").pop() ?? "review"}`;
}

/**
 * A session left over from an earlier `/diff` still holds its notes in memory,
 * so they are read before its tab is closed — closing would discard them.
 */
async function drainPreviousSession(pi: ExtensionAPI, worktreeDir: string): Promise<UserNote[]> {
	const existing = await getHunkSession(pi, worktreeDir);
	const notes = existing.found ? await readUserNotes(pi, worktreeDir) : [];
	const staleTab = forgetTab(worktreeDir);
	if (staleTab) await closeHerdrTab(pi, staleTab);
	return notes;
}

function hunkArgv(base: string, worktreeDir: string): string[] {
	const argv = ["hunk", "diff", base];
	const sidecar = sidecarPath(worktreeDir);
	if (fs.existsSync(sidecar)) argv.push("--agent-context", sidecar);
	return argv;
}

async function runDiff(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const ineligible = checkHerdrEligibility({ env: process.env, hasUI: ctx.hasUI, subject: "diffs" });
	if (ineligible) {
		ctx.ui.notify(`/diff is unavailable: ${ineligible.detail}`, "error");
		return;
	}

	const availability = await detectHunk(pi);
	if (!availability.available) {
		ctx.ui.notify(availability.message, "error");
		return;
	}

	const workspaceId = process.env.HERDR_WORKSPACE_ID;
	if (!workspaceId) {
		ctx.ui.notify("/diff is unavailable: missing Herdr workspace id.", "error");
		return;
	}

	const worktreeDir = worktreeDirFor(ctx);
	let base: string;
	try {
		base = await resolveReviewBase(pi, worktreeDir);
	} catch (err) {
		ctx.ui.notify(`/diff could not resolve the review base: ${errorMessage(err)}`, "error");
		return;
	}

	const carried = await drainPreviousSession(pi, worktreeDir);

	const tab = await openHerdrTab(pi, {
		workspaceId,
		cwd: worktreeDir,
		label: tabLabel(worktreeDir),
		env: HUNK_TAB_ENV,
	});
	if (tab.status !== "ok") {
		ctx.ui.notify(`/diff could not open a Herdr tab: ${tab.message}`, "error");
		return;
	}
	rememberTab(worktreeDir, tab.value.tabId);

	const launched = await runInHerdrPane(pi, tab.value.paneId, hunkArgv(base, worktreeDir));
	if (launched.status !== "ok") {
		await closeHerdrTab(pi, tab.value.tabId);
		forgetTab(worktreeDir);
		ctx.ui.notify(`/diff could not start hunk: ${launched.message}`, "error");
		return;
	}

	// The confirm blocks until the user comes back, which is what keeps the read
	// ahead of the quit: hunk's notes live in memory and die with its window.
	await withHerdrBlocked(pi, "Reviewing in hunk", () =>
		ctx.ui.confirm("Reviewing in hunk", "Annotate the diff with `c`, then confirm here to send your notes back."),
	);

	// Read on cancel too: notes already written are the user's, not a draft.
	const notes = [...carried, ...(await readUserNotes(pi, worktreeDir))];
	await closeHerdrTab(pi, tab.value.tabId);
	forgetTab(worktreeDir);

	if (notes.length === 0) {
		ctx.ui.notify("No annotations were left on the diff.", "info");
		return;
	}
	pi.sendMessage({ customType: "diff-annotations", content: formatAnnotations(notes), display: true });
}

export function registerDiffCommand(pi: ExtensionAPI): void {
	if (isSubagent()) return;

	pi.registerCommand("diff", {
		description: "Review this branch's changes in hunk and send your annotations back",
		handler: async (_args, ctx) => {
			await runDiff(pi, ctx);
		},
	});
}
