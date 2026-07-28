/** `/diff` — review this branch's changes in hunk and bring the annotations back. */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { gitOutput, isMergedInto, resolveReviewBase } from "#core/git/repo.ts";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { checkHerdrEligibility, closeHerdrTab, openHerdrTab, runInHerdrPane } from "#core/ui/herdr-pane.ts";
import { formatAnnotations } from "./annotations.ts";
import { type Checkpoint, forgetCheckpoint, recordCheckpoint, validateCheckpoint } from "./checkpoints.ts";
import { detectHunk, type HunkSession, listHunkSessions, readUserNotes, type UserNote } from "./hunk.ts";
import { type DiffModeKind, parseDiffArgs } from "./mode.ts";
import { attachSession, forgetSession, forgetTab, ownedReview, rememberTab } from "./session-state.ts";
import { clearSidecar, readSidecarBase, sidecarPath } from "./sidecar.ts";
import { reviewWorktreeDir } from "./worktree.ts";

// hunk's own update nag would render inside a tab Basecamp owns.
const HUNK_TAB_ENV = { HUNK_DISABLE_UPDATE_NOTICE: "1" };

/** Generous enough for a cold Node TUI to boot and register. */
export interface LaunchPoll {
	attempts: number;
	intervalMs: number;
}
const DEFAULT_LAUNCH_POLL: LaunchPoll = { attempts: 24, intervalMs: 250 };

function tabLabel(worktreeDir: string, mode: DiffModeKind): string {
	const label = getBasecampEnv("BASECAMP_WORKTREE_LABEL") ?? worktreeDir.split("/").pop() ?? "review";
	return mode === "last" ? `diff: ${label} (last)` : `diff: ${label}`;
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

	// A tab that never registered a session holds no notes, so a close that fails
	// — which `herdr tab close` does deterministically once the tab is gone — is
	// not worth stopping for. Blocking here would strand every later call.
	if (!(await closeAndForget(pi, worktreeDir, owned.tabId))) forgetTab(worktreeDir);
	return { notes: [] };
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

interface HunkLaunch {
	argv: string[];
	/** Whether this launch actually renders the stored rationale. */
	sidecarAttached: boolean;
}

/**
 * The sidecar is attached by **span identity**, not by diff target: annotation
 * ranges are recorded against the *new* side of the diff, which is the working
 * tree in every mode, so rationale written for this branch state is valid in a
 * full review and an incremental one alike. What must match is the review base
 * — worktree directories are reused across branches, and a stamp from another
 * branch would render its rationale against these line numbers.
 *
 * Comparing against the launch target instead would silently never match on a
 * feature branch, because the annotate-time base and a `/diff last` target are
 * different quantities.
 */
function hunkLaunch(target: string, base: string, worktreeDir: string): HunkLaunch {
	const argv = ["hunk", "diff", target];
	const sidecarAttached = readSidecarBase(worktreeDir) === base;
	if (sidecarAttached) argv.push("--agent-context", sidecarPath(worktreeDir));
	return { argv, sidecarAttached };
}

function deliver(pi: ExtensionAPI, ctx: ExtensionContext, notes: UserNote[]): void {
	if (notes.length === 0) {
		ctx.ui.notify("No annotations were left on the diff.", "info");
		return;
	}
	// A user prompt, not a custom injection: these are the user's own review
	// comments, so they arrive as if the user typed them — the agent weighs
	// them like any other instruction from the user, not like extension output.
	// Only annotations the user actually wrote reach here, which is what makes
	// speaking as the user honest; an empty review returns above without a turn.
	void Promise.resolve(pi.sendUserMessage(formatAnnotations(notes), { deliverAs: "followUp" })).catch(() => {
		ctx.ui.notify("/diff could not deliver your annotations to the agent.", "error");
	});
}

interface DiffTarget {
	/** The single argument handed to `hunk diff`. */
	target: string;
	/** Current merge-base — what the checkpoint is recorded against. */
	base: string;
	/** HEAD at launch — what a completed base review records. */
	head: string;
	/** Whether a completed review advances the checkpoint (only base reviews do). */
	advances: boolean;
}

/**
 * What the review should diff against. `/diff` shows everything since the
 * merge-base; `/diff last` shows only what moved since the last completed
 * `/diff` — user-initiated checkpoints, by SHA under the clean-tree
 * assumption. A checkpoint is followed only while the merge-base it was
 * recorded against still resolves: worktree directories are reused across
 * branches, and a checkpoint taken on one branch is meaningless on another.
 *
 * `/diff last` never advances the checkpoint — it is a look back at the same
 * span, so running it twice shows the same incremental diff. With no
 * surviving checkpoint it degrades to a base review (which then records),
 * because the only thing it could mean is "everything".
 */
async function resolveDiffTarget(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	worktreeDir: string,
	mode: DiffModeKind,
): Promise<DiffTarget | null> {
	let base: string;
	let head: string;
	try {
		base = await resolveReviewBase(pi, worktreeDir);
		head = await gitOutput(pi, worktreeDir, ["rev-parse", "HEAD"]);
	} catch (err) {
		ctx.ui.notify(`/diff could not resolve the review base: ${errorMessage(err)}`, "error");
		return null;
	}

	const checkpoint = validateCheckpoint(worktreeDir, base);
	// Base equality alone would let a checkpoint from a sibling branch survive:
	// branches cut from the same default-branch tip share a merge-base. Requiring
	// ancestry also covers amend/rebase, where the recorded commit is orphaned and
	// `git diff <orphan>` would present the rewritten work as reversals.
	if (mode === "last" && checkpoint && (await isMergedInto(pi, worktreeDir, checkpoint.last, "HEAD"))) {
		return { target: checkpoint.last, base, head, advances: false };
	}
	if (mode === "last") {
		if (checkpoint) forgetCheckpoint(worktreeDir);
		const reason = checkpoint ? "its checkpoint is no longer in this branch's history" : "no checkpoint recorded yet";
		ctx.ui.notify(`/diff last: ${reason} — showing the full diff.`, "info");
	}
	return { target: base, base, head, advances: true };
}

/**
 * The review ended with its notes safely read, so a base review moves the
 * checkpoint up to HEAD. The sidecar is consumed **only when this review
 * actually rendered it** — clearing rationale the launch never attached would
 * destroy it unread, so an unattached sidecar is left for the review that can
 * show it. On any earlier failure neither happens, and a retry sees the same
 * span with its rationale intact.
 */
function consumeReview(worktreeDir: string, resolved: DiffTarget, sidecarAttached: boolean): void {
	if (sidecarAttached) clearSidecar(worktreeDir);
	if (resolved.advances) {
		const checkpoint: Checkpoint = { base: resolved.base, last: resolved.head };
		recordCheckpoint(worktreeDir, checkpoint);
	}
}

async function runDiff(pi: ExtensionAPI, ctx: ExtensionContext, poll: LaunchPoll, mode: DiffModeKind): Promise<void> {
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
	const resolved = await resolveDiffTarget(pi, ctx, worktreeDir, mode);
	if (!resolved) return;

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
		label: tabLabel(worktreeDir, mode),
		env: HUNK_TAB_ENV,
	});
	if (tab.status !== "ok") {
		deliver(pi, ctx, drained.notes);
		ctx.ui.notify(`/diff could not open a Herdr tab: ${tab.message}`, "error");
		return;
	}
	rememberTab(worktreeDir, tab.value.tabId);

	const launch = hunkLaunch(resolved.target, resolved.base, worktreeDir);
	const launched = await runInHerdrPane(pi, tab.value.paneId, launch.argv);
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
	// Deliver before consuming: the notes exist only in memory until they are
	// sent, so a failure while clearing state must not be able to lose them.
	deliver(pi, ctx, [...drained.notes, ...read.notes]);
	consumeReview(worktreeDir, resolved, launch.sidecarAttached);
}

export function registerDiffCommand(pi: ExtensionAPI, poll: LaunchPoll = DEFAULT_LAUNCH_POLL): void {
	if (isSubagent()) return;

	pi.registerCommand("diff", {
		description:
			"Review this branch's changes in hunk and send your annotations back; `/diff last` reviews only what changed since your last /diff",
		handler: async (args, ctx) => {
			const mode = parseDiffArgs(args);
			if (mode.kind === "invalid") {
				ctx.ui.notify(`Unknown /diff argument "${mode.arg}" — expected nothing or "last".`, "error");
				return;
			}
			await runDiff(pi, ctx, poll, mode.kind);
		},
	});
}
