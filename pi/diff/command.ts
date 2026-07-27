/** `/diff` — review this branch's changes in hunk and bring the annotations back. */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { resolveReviewBase } from "#core/git/repo.ts";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { checkHerdrEligibility, closeHerdrTab, openHerdrTab, runInHerdrPane } from "#core/ui/herdr-pane.ts";
import { formatAnnotations } from "./annotations.ts";
import { detectHunk, type HunkSession, listHunkSessions, readUserNotes, type UserNote } from "./hunk.ts";
import { attachSession, forgetSession, forgetTab, ownedReview, rememberTab } from "./session-state.ts";
import { readSidecarBase, sidecarPath } from "./sidecar.ts";
import { reviewWorktreeDir } from "./worktree.ts";

// hunk's own update nag would render inside a tab Basecamp owns.
const HUNK_TAB_ENV = { HUNK_DISABLE_UPDATE_NOTICE: "1" };

/** Generous enough for a cold Node TUI to boot and register. */
export interface LaunchPoll {
	attempts: number;
	intervalMs: number;
}
const DEFAULT_LAUNCH_POLL: LaunchPoll = { attempts: 24, intervalMs: 250 };

function tabLabel(worktreeDir: string): string {
	return `diff: ${getBasecampEnv("BASECAMP_WORKTREE_LABEL") ?? worktreeDir.split("/").pop() ?? "review"}`;
}

interface Drained {
	notes: UserNote[];
	/** A live review we could not safely replace; stop rather than destroy it. */
	blocked?: string;
	/** A review whose window is already gone, so its notes are unrecoverable. */
	lost?: boolean;
}

/**
 * A review left over from an earlier `/diff` still holds its notes in memory,
 * so they are read before its tab is closed — closing would discard them.
 *
 * Only a review this process opened is drained; a hunk the user launched
 * themselves is left alone rather than reported as if it were this review.
 *
 * A read that fails against a *live* session blocks, because closing would
 * destroy notes we could not recover. A session that is no longer registered
 * is the opposite case: quitting hunk without confirming already lost those
 * notes, so the id is cleared and the caller carries on. Retaining it would
 * fail identically on every future call, and the state survives /reload.
 */
async function drainOwnedReview(pi: ExtensionAPI, worktreeDir: string, live: HunkSession[]): Promise<Drained> {
	const owned = ownedReview(worktreeDir);
	if (!owned) return { notes: [] };

	const sessionAlive = owned.sessionId !== undefined && live.some((s) => s.sessionId === owned.sessionId);

	if (owned.sessionId !== undefined && !sessionAlive) {
		if (!(await closeAndForget(pi, worktreeDir, owned.tabId))) forgetSession(worktreeDir);
		return { notes: [], lost: true };
	}

	if (sessionAlive && owned.sessionId !== undefined) {
		const read = await readUserNotes(pi, owned.sessionId);
		if (!read.ok) {
			return { notes: [], blocked: `could not read the previous review's notes (${read.reason})` };
		}
		if (await closeAndForget(pi, worktreeDir, owned.tabId)) return { notes: read.notes };
		return { notes: read.notes, blocked: "could not close the previous review's tab" };
	}

	if (await closeAndForget(pi, worktreeDir, owned.tabId)) return { notes: [] };
	return { notes: [], blocked: "could not close the previous review's tab" };
}

/** Keeps the ids whenever the close fails, so a later run can still reclaim the tab. */
async function closeAndForget(pi: ExtensionAPI, worktreeDir: string, tabId: string): Promise<boolean> {
	const closed = await closeHerdrTab(pi, tabId);
	if (closed.status === "ok") forgetTab(worktreeDir);
	return closed.status === "ok";
}

/**
 * `pane run` only proves the keystrokes reached a shell, so hunk is polled
 * until it registers with its daemon. The session is identified by diffing
 * against the ids present beforehand, which stays correct when the user has
 * their own hunk open on the same worktree.
 */
async function awaitLaunchedSession(
	pi: ExtensionAPI,
	worktreeDir: string,
	before: ReadonlySet<string>,
	poll: LaunchPoll,
): Promise<HunkSession | null> {
	for (let attempt = 0; attempt < poll.attempts; attempt++) {
		await new Promise((resolve) => setTimeout(resolve, poll.intervalMs));
		const fresh = (await listHunkSessions(pi, worktreeDir)).filter((s) => !before.has(s.sessionId));
		if (fresh.length > 0) return fresh[fresh.length - 1] ?? null;
	}
	return null;
}

/**
 * The sidecar is attached only while it still describes this base. Worktree
 * directories are reused across branches, so an unstamped match would render
 * one branch's rationale against another branch's line numbers.
 */
function hunkArgv(base: string, worktreeDir: string): string[] {
	const argv = ["hunk", "diff", base];
	if (readSidecarBase(worktreeDir) === base) argv.push("--agent-context", sidecarPath(worktreeDir));
	return argv;
}

function deliver(pi: ExtensionAPI, ctx: ExtensionContext, notes: UserNote[]): void {
	if (notes.length === 0) {
		ctx.ui.notify("No annotations were left on the diff.", "info");
		return;
	}
	pi.sendMessage(
		{ customType: "diff-annotations", content: formatAnnotations(notes), display: true },
		{ deliverAs: "followUp" },
	);
}

async function runDiff(pi: ExtensionAPI, ctx: ExtensionContext, poll: LaunchPoll): Promise<void> {
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

	const worktreeDir = reviewWorktreeDir();
	let base: string;
	try {
		base = await resolveReviewBase(pi, worktreeDir);
	} catch (err) {
		ctx.ui.notify(`/diff could not resolve the review base: ${errorMessage(err)}`, "error");
		return;
	}

	const live = await listHunkSessions(pi, worktreeDir);
	const drained = await drainOwnedReview(pi, worktreeDir, live);
	if (drained.blocked) {
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify(`/diff stopped: ${drained.blocked}. The hunk window is still open.`, "error");
		return;
	}
	if (drained.lost) {
		ctx.ui.notify("The previous review's notes were lost — hunk was closed before confirming here.", "warning");
	}

	const before = new Set(live.map((s) => s.sessionId));

	const tab = await openHerdrTab(pi, {
		workspaceId,
		cwd: worktreeDir,
		label: tabLabel(worktreeDir),
		env: HUNK_TAB_ENV,
	});
	if (tab.status !== "ok") {
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify(`/diff could not open a Herdr tab: ${tab.message}`, "error");
		return;
	}
	rememberTab(worktreeDir, tab.value.tabId);

	const launched = await runInHerdrPane(pi, tab.value.paneId, hunkArgv(base, worktreeDir));
	if (launched.status !== "ok") {
		await closeAndForget(pi, worktreeDir, tab.value.tabId);
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify(`/diff could not start hunk: ${launched.message}`, "error");
		return;
	}

	const session = await awaitLaunchedSession(pi, worktreeDir, before, poll);
	if (!session) {
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify("/diff started hunk but it never registered a session — check the diff tab for its error.", "error");
		return;
	}
	attachSession(worktreeDir, session.sessionId);

	// The confirm blocks until the user comes back, which is what keeps the read
	// ahead of the quit: hunk's notes live in memory and die with its window.
	await withHerdrBlocked(pi, "Reviewing in hunk", () =>
		ctx.ui.confirm("Reviewing in hunk", "Annotate the diff with `c`, then confirm here to send your notes back."),
	);

	// Read on cancel too: notes already written are the user's, not a draft.
	const read = await readUserNotes(pi, session.sessionId);
	if (!read.ok) {
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify(
			`/diff could not read your annotations (${read.reason}). The hunk window is still open so they are not lost.`,
			"error",
		);
		return;
	}

	await closeAndForget(pi, worktreeDir, tab.value.tabId);
	deliver(pi, ctx, [...drained.notes, ...read.notes]);
}

export function registerDiffCommand(pi: ExtensionAPI, poll: LaunchPoll = DEFAULT_LAUNCH_POLL): void {
	if (isSubagent()) return;

	pi.registerCommand("diff", {
		description: "Review this branch's changes in hunk and send your annotations back",
		handler: async (_args, ctx) => {
			await runDiff(pi, ctx, poll);
		},
	});
}
