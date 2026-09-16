import type { ExtensionAPI, ExtensionCommandContext } from "@oh-my-pi/pi-coding-agent";
import type { DiffAnnotation } from "./annotations.ts";
import { buildDiffReviewArtifact, type PersistedDiffReview, persistDiffReview } from "./artifact.ts";
import {
	checkHerdrEligibility,
	closeHerdrPane,
	readHerdrPaneProcesses,
	runInHerdrPane,
	splitHerdrPane,
	withHerdrBlocked,
} from "./herdr.ts";
import {
	awaitLaunchedSession,
	detectHunk,
	type LaunchPoll,
	listHunkSessions,
	readUserNotes,
	type UserNote,
} from "./hunk-cli.ts";
import { activeAnnotations, recordDiffCompleted } from "./journal.ts";
import { type DiffSnapshot, type LoadDiff, loadDiff } from "./loader.ts";
import { type AgentContextHandle, type TemporaryHunkFile, writeAgentContext, writeReviewPatch } from "./sidecar.ts";
import { revalidateAnnotations } from "./validate.ts";

const HUNK_PANE_ENV = { HUNK_DISABLE_UPDATE_NOTICE: "1" };
const DEFAULT_LAUNCH_POLL: LaunchPoll = { attempts: 24, intervalMs: 250 };

export interface DiffCommandDeps {
	loadDiff?: LoadDiff;
	poll?: LaunchPoll;
	writeAgentContext?: (annotations: readonly DiffAnnotation[]) => AgentContextHandle;
	writeReviewPatch?: (patch: string) => TemporaryHunkFile;
}

function rangeSpan(range: [number, number]): string {
	return range[0] === range[1] ? `${range[0]}` : `${range[0]}-${range[1]}`;
}

function noteLocation(note: UserNote): string {
	if (note.newRange && note.oldRange) {
		return `${note.filePath}:${rangeSpan(note.newRange)} (new lines) and ${note.filePath}:${rangeSpan(note.oldRange)} (removed lines)`;
	}
	if (note.newRange) return `${note.filePath}:${rangeSpan(note.newRange)}`;
	if (note.oldRange) return `${note.filePath}:${rangeSpan(note.oldRange)} (removed lines)`;
	return note.filePath;
}

export function formatUserAnnotations(notes: readonly UserNote[], reviewRef: string): string {
	const entries = notes.map((note) => `- ${noteLocation(note)}\n  ${note.body.trim().split("\n").join("\n  ")}`);
	return [
		`I reviewed the diff and left ${notes.length} annotation${notes.length === 1 ? "" : "s"}:`,
		"",
		...entries,
		"",
		`Review record: ${reviewRef}`,
		"",
		"Address these together with me — discuss before editing.",
	].join("\n");
}

function notifyFailure(ctx: ExtensionCommandContext, prefix: string, error: unknown): void {
	const message = error instanceof Error ? error.message : String(error);
	ctx.ui.notify(`${prefix}: ${message}`, "error");
}

function cleanupTemporaryFiles(ctx: ExtensionCommandContext, ...files: (TemporaryHunkFile | undefined)[]): void {
	for (const file of files) {
		if (!file) continue;
		try {
			file.cleanup();
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			ctx.ui.notify(`/diff could not remove a temporary Hunk input: ${message}`, "warning");
		}
	}
}

async function readHunkPanePids(
	pi: ExtensionAPI,
	paneId: string,
	frozenPatchPath: string,
): Promise<ReadonlySet<number>> {
	const processes = await readHerdrPaneProcesses(pi, paneId);
	if (processes.status === "failed") {
		throw new Error(processes.error ?? processes.stderr ?? processes.message);
	}
	return new Set(
		processes.value
			.filter((process) => process.argv.includes("patch") && process.argv.includes(frozenPatchPath))
			.map((process) => process.pid),
	);
}

function ownsOrigin(ctx: ExtensionCommandContext, sessionId: string, leafId: string | undefined): boolean {
	if (ctx.sessionManager.getSessionId() !== sessionId) return false;
	return leafId === undefined || ctx.sessionManager.getBranch().some((entry) => entry.id === leafId);
}

/** Register one frozen Hunk review transaction. */
export default function registerDiffCommand(pi: ExtensionAPI, deps: DiffCommandDeps = {}): void {
	const writeContext = deps.writeAgentContext ?? writeAgentContext;
	const writePatch = deps.writeReviewPatch ?? writeReviewPatch;
	const load = deps.loadDiff ?? loadDiff;
	const poll = deps.poll ?? DEFAULT_LAUNCH_POLL;
	const appendEntry = (customType: string, data?: unknown): void => pi.appendEntry(customType, data);

	pi.registerCommand("diff", {
		description: "Review this branch's diff in Hunk and send inline annotations back to the agent",
		handler: async (args, ctx) => {
			if (args.trim() !== "") {
				ctx.ui.notify("/diff takes no arguments.", "error");
				return;
			}
			await ctx.waitForIdle();
			if (ctx.mode !== "tui") {
				ctx.ui.notify("/diff is available only in an interactive TUI session.", "error");
				return;
			}
			const ineligible = checkHerdrEligibility({
				env: {
					HERDR_ENV: process.env.HERDR_ENV,
					HERDR_SOCKET_PATH: process.env.HERDR_SOCKET_PATH,
					HERDR_PANE_ID: process.env.HERDR_PANE_ID,
					HERDR_WORKSPACE_ID: process.env.HERDR_WORKSPACE_ID,
				},
				hasUI: ctx.hasUI,
			});
			if (ineligible) {
				ctx.ui.notify(`/diff is unavailable: ${ineligible.detail}`, "error");
				return;
			}

			const originSessionId = ctx.sessionManager.getSessionId();
			let snapshot: DiffSnapshot;
			try {
				snapshot = await load(ctx.cwd);
			} catch (error) {
				notifyFailure(ctx, "/diff could not load the branch diff", error);
				return;
			}
			for (const warning of snapshot.warnings ?? []) ctx.ui.notify(warning, "warning");
			if (snapshot.patch.length === 0) {
				ctx.ui.notify("No reviewable changes.", "info");
				return;
			}

			const availability = await detectHunk(pi, snapshot.repositoryRoot);
			if (!availability.available) {
				ctx.ui.notify(availability.message, "error");
				return;
			}
			const binary = availability.binary;
			const baseline = await listHunkSessions(pi, binary);
			if (!baseline.ok) {
				ctx.ui.notify(`/diff could not discover Hunk sessions: ${baseline.reason}`, "error");
				return;
			}

			if (ctx.sessionManager.getSessionId() !== originSessionId) {
				ctx.ui.notify("/diff stopped because the originating OMP session changed.", "error");
				return;
			}
			const journalBranch = ctx.sessionManager.getBranch();
			const journalCutoffId = journalBranch.at(-1)?.id;
			const journaled = activeAnnotations(journalBranch);
			const { current, stale } = await revalidateAnnotations(snapshot, journaled);
			if (stale.length > 0) {
				ctx.ui.notify(
					`Discarded ${stale.length} agent annotation${stale.length === 1 ? "" : "s"} for this review because the target changed: ${stale.map((annotation) => annotation.id).join(", ")}.`,
					"warning",
				);
			}

			let reviewPatch: TemporaryHunkFile | undefined;
			let agentContext: AgentContextHandle | undefined;
			try {
				reviewPatch = writePatch(snapshot.patch);
				if (current.length > 0) agentContext = writeContext(current);
			} catch (error) {
				cleanupTemporaryFiles(ctx, reviewPatch, agentContext);
				notifyFailure(ctx, "/diff could not prepare the frozen Hunk review", error);
				return;
			}
			if (!reviewPatch) {
				ctx.ui.notify("/diff could not prepare the frozen Hunk review.", "error");
				return;
			}

			const pane = await splitHerdrPane(pi, {
				paneId: process.env.HERDR_PANE_ID as string,
				cwd: snapshot.repositoryRoot,
				env: HUNK_PANE_ENV,
			});
			if (pane.status === "failed") {
				cleanupTemporaryFiles(ctx, reviewPatch, agentContext);
				ctx.ui.notify(`/diff could not split a Herdr pane: ${pane.message}`, "error");
				return;
			}
			const argv = [binary.executable, "patch", reviewPatch.path];
			if (agentContext) argv.push("--agent-context", agentContext.path, "--agent-notes");
			const launched = await runInHerdrPane(pi, pane.value.paneId, argv);
			if (launched.status === "failed") {
				ctx.ui.notify(
					`/diff could not confirm that Hunk started: ${launched.message} The pane and its private launch inputs remain available because Hunk may still start.`,
					"error",
				);
				return;
			}

			const before = new Set(baseline.sessions.map((session) => session.sessionId));
			const discovery = await awaitLaunchedSession(pi, binary, undefined, before, poll, undefined, () =>
				readHunkPanePids(pi, pane.value.paneId, reviewPatch.path),
			);
			cleanupTemporaryFiles(ctx, reviewPatch, agentContext);
			if (!discovery.ok || !discovery.session) {
				const reason = discovery.ok ? "Hunk never registered a review session" : discovery.reason;
				ctx.ui.notify(`/diff could not identify the Hunk review: ${reason}. The pane remains open.`, "error");
				return;
			}

			const confirmed = await withHerdrBlocked(pi, "Reviewing in Hunk", () =>
				ctx.ui.confirm(
					"Reviewing in Hunk",
					"Annotate the diff with `c`, then return here. Confirm submits the review; cancelling still captures notes already written.",
				),
			);
			const read = await readUserNotes(pi, binary, discovery.session.sessionId);
			if (!read.ok) {
				ctx.ui.notify(
					`/diff could not read your annotations (${read.reason}). The Hunk pane is still open so they are not lost.`,
					"error",
				);
				return;
			}

			if (!ownsOrigin(ctx, originSessionId, journalCutoffId)) {
				ctx.ui.notify(
					"/diff stopped because the originating OMP session or branch changed. The Hunk pane remains open.",
					"error",
				);
				return;
			}
			let persisted: PersistedDiffReview;
			try {
				const artifact = buildDiffReviewArtifact(
					snapshot,
					confirmed ? "submitted" : "cancelled",
					read.notes,
					current.map((annotation) => annotation.id),
					stale.map((annotation) => annotation.id),
				);
				persisted = await persistDiffReview(ctx.sessionManager, artifact);
			} catch (error) {
				notifyFailure(ctx, "/diff could not save your review; the Hunk pane remains open", error);
				return;
			}
			if (!ownsOrigin(ctx, originSessionId, journalCutoffId)) {
				ctx.ui.notify(
					`/diff saved the review at ${persisted.reviewRef}, but the originating OMP session or branch changed. The Hunk pane remains open and no journal state was consumed.`,
					"error",
				);
				return;
			}

			const closed = await closeHerdrPane(pi, pane.value.paneId);
			if (closed.status === "failed") {
				ctx.ui.notify(`${closed.message} Your captured review is safe at ${persisted.reviewRef}.`, "warning");
			}
			if (!ownsOrigin(ctx, originSessionId, journalCutoffId)) {
				ctx.ui.notify(
					`/diff saved the review at ${persisted.reviewRef}, but the originating OMP session or branch changed before delivery. No journal state was consumed.`,
					"error",
				);
				return;
			}
			try {
				recordDiffCompleted(appendEntry, persisted.reviewRef, journalCutoffId);
			} catch (error) {
				notifyFailure(ctx, "/diff saved the review but could not record its session boundary", error);
			}

			if (read.notes.length > 0) {
				pi.sendUserMessage(formatUserAnnotations(read.notes, persisted.reviewRef));
			} else {
				ctx.ui.notify(`No annotations were left on the diff. Review record: ${persisted.reviewRef}`, "info");
			}
		},
	});
}
