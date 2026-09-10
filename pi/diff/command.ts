/** `/diff` — review this branch's changes in hunk and bring the annotations back. */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { gitOutput, isMergedInto, resolveReviewBase } from "#core/git/repo.ts";
import { isSubagent } from "#core/host/env.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { checkHerdrEligibility, runInHerdrPane, splitHerdrPane } from "#core/ui/herdr-pane.ts";
import { formatAnnotations } from "./annotations.ts";
import { type Checkpoint, forgetCheckpoint, recordCheckpoint, validateCheckpoint } from "./checkpoints.ts";
import { detectHunk, type HunkBinary, listHunkSessions, readUserNotes, type UserNote } from "./hunk.ts";
import { type DiffModeKind, parseDiffArgs } from "./mode.ts";
import { awaitLaunchedSession, closeAndForget, drainOwnedReview, type LaunchPoll } from "./review-session.ts";
import { attachSession, rememberPane } from "./session-state.ts";
import { clearSidecar, readSidecarBase, sidecarPath } from "./sidecar.ts";
import { reviewWorktreeDir } from "./worktree.ts";

// hunk's own update nag would render inside a pane Basecamp owns.
const HUNK_PANE_ENV = { HUNK_DISABLE_UPDATE_NOTICE: "1" };

/** Generous enough for a cold TUI to boot and register. */
const DEFAULT_LAUNCH_POLL: LaunchPoll = { attempts: 24, intervalMs: 250 };

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
function hunkLaunch(binary: HunkBinary, target: string, base: string, worktreeDir: string): HunkLaunch {
	const argv = [binary.executable, "diff", target];
	const sidecarAttached = readSidecarBase(worktreeDir) === base;
	if (sidecarAttached) argv.push("--agent-context", sidecarPath(worktreeDir));
	return { argv, sidecarAttached };
}

function deliver(pi: ExtensionAPI, notes: UserNote[]): void {
	if (notes.length === 0) return;
	// A user prompt, not a custom injection: these are the user's own review
	// comments, so they arrive as if the user typed them — the agent weighs
	// them like any other instruction from the user, not like extension output.
	// Only annotations the user actually wrote reach here, which is what makes
	// speaking as the user honest; an empty review returns above without a turn.
	// Handing the message over is synchronous on this surface, and the session
	// reports its own delivery failures, so there is no local result to inspect.
	pi.sendUserMessage(formatAnnotations(notes), { deliverAs: "followUp" });
}

function reportDiscoveryFailure(ctx: ExtensionContext, binary: HunkBinary, reason: string): void {
	ctx.ui.notify(
		`/diff could not discover hunk sessions using ${binary.executable} (${binary.version}): ${reason}. ` +
			"Unread review panes have been left open. Check that Pi and your shell use the same hunk installation; " +
			"after an upgrade, save any review notes and restart Pi from a fresh shell.",
		"error",
	);
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

	const worktreeDir = reviewWorktreeDir();
	const availability = await detectHunk(pi, worktreeDir);
	if (!availability.available) {
		ctx.ui.notify(availability.message, "error");
		return;
	}

	const paneId = process.env.HERDR_PANE_ID;
	if (!paneId) {
		ctx.ui.notify("/diff is unavailable: missing Herdr pane id.", "error");
		return;
	}

	const binary = availability.binary;
	const live = await listHunkSessions(pi, binary, worktreeDir);
	if (!live.ok) {
		reportDiscoveryFailure(ctx, binary, live.reason);
		return;
	}
	const resolved = await resolveDiffTarget(pi, ctx, worktreeDir, mode);
	if (!resolved) return;

	const drained = await drainOwnedReview(pi, binary, worktreeDir, live.sessions);
	if (drained.blocked) {
		deliver(pi, drained.notes);
		ctx.ui.notify(`/diff stopped: ${drained.blocked}. The hunk pane is still open.`, "error");
		return;
	}
	if (drained.lost) {
		ctx.ui.notify("The previous review's notes were lost — hunk was closed before confirming here.", "warning");
	}
	if (drained.notes.length > 0) {
		// Delivery starts an agent turn; opening another review now would let the
		// agent edit the same files while the user is reviewing them.
		ctx.ui.notify("Recovered the previous review's annotations. Run /diff again after the agent handles them.", "info");
		deliver(pi, drained.notes);
		return;
	}

	const before = new Set(live.sessions.map((s) => s.sessionId));

	const pane = await splitHerdrPane(pi, {
		paneId,
		cwd: worktreeDir,
		env: HUNK_PANE_ENV,
	});
	if (pane.status !== "ok") {
		ctx.ui.notify(`/diff could not split a Herdr pane: ${pane.message}`, "error");
		return;
	}
	rememberPane(worktreeDir, pane.value.paneId, before);

	const launch = hunkLaunch(binary, resolved.target, resolved.base, worktreeDir);
	const launched = await runInHerdrPane(pi, pane.value.paneId, launch.argv);
	if (launched.status !== "ok") {
		await closeAndForget(pi, worktreeDir, pane.value.paneId);
		ctx.ui.notify(`/diff could not start hunk: ${launched.message}`, "error");
		return;
	}

	const discovery = await awaitLaunchedSession(pi, binary, worktreeDir, before, poll);
	if (!discovery.ok) {
		reportDiscoveryFailure(ctx, binary, discovery.reason);
		return;
	}
	const session = discovery.session;
	if (!session) {
		ctx.ui.notify("/diff started hunk but it never registered a session — check the diff pane for its error.", "error");
		return;
	}
	attachSession(worktreeDir, session.sessionId);

	// The confirm blocks until the user comes back, which is what keeps the read
	// ahead of the quit: hunk's notes live in memory and die with its window.
	await withHerdrBlocked(pi, "Reviewing in hunk", () =>
		ctx.ui.confirm("Reviewing in hunk", "Annotate the diff with `c`, then confirm here to send your notes back."),
	);

	// Read on cancel too: notes already written are the user's, not a draft.
	const read = await readUserNotes(pi, binary, session.sessionId);
	if (!read.ok) {
		ctx.ui.notify(
			`/diff could not read your annotations (${read.reason}). The hunk pane is still open so they are not lost.`,
			"error",
		);
		return;
	}

	await closeAndForget(pi, worktreeDir, pane.value.paneId);
	// Hand the notes over before touching local state: hunk's pane is already
	// closed, so this is the only copy, and clearing the sidecar can still throw
	// on a permissions or busy error.
	deliver(pi, read.notes);
	if (read.notes.length === 0) ctx.ui.notify("No annotations were left on the diff.", "info");
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
