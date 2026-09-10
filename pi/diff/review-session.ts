import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { closeHerdrPane, runHerdr } from "#core/ui/herdr-pane.ts";
import { type HunkBinary, type HunkSession, listHunkSessions, readUserNotes, type UserNote } from "./hunk.ts";
import { attachSession, forgetPane, ownedReview } from "./session-state.ts";

export interface LaunchPoll {
	attempts: number;
	intervalMs: number;
}

interface Drained {
	notes: UserNote[];
	blocked?: string;
	lost?: boolean;
}

type SessionDiscovery = { ok: true; session: HunkSession | null } | { ok: false; reason: string };

function discoverSession(live: HunkSession[], before: ReadonlySet<string>): SessionDiscovery {
	const fresh = live.filter((session) => !before.has(session.sessionId));
	if (fresh.length > 1)
		return { ok: false, reason: "multiple new hunk sessions appeared; cannot identify this review" };
	return { ok: true, session: fresh[0] ?? null };
}

/** A shell accepting the launch command does not prove hunk registered. */
export async function awaitLaunchedSession(
	pi: ExtensionAPI,
	binary: HunkBinary,
	worktreeDir: string,
	before: ReadonlySet<string>,
	poll: LaunchPoll,
): Promise<SessionDiscovery> {
	let lastAttempt: SessionDiscovery = { ok: true, session: null };
	for (let attempt = 0; attempt < poll.attempts; attempt++) {
		await new Promise((resolve) => setTimeout(resolve, poll.intervalMs));
		const read = await listHunkSessions(pi, binary, worktreeDir);
		if (!read.ok) {
			// A cold daemon may accept connections before its health endpoint is ready.
			lastAttempt = read;
			continue;
		}
		lastAttempt = discoverSession(read.sessions, before);
		if (!lastAttempt.ok || lastAttempt.session) return lastAttempt;
	}
	return lastAttempt;
}

export async function closeAndForget(pi: ExtensionAPI, worktreeDir: string, paneId: string): Promise<boolean> {
	const closed = await closeHerdrPane(pi, paneId);
	if (closed.status === "ok") forgetPane(worktreeDir);
	return closed.status === "ok";
}

async function paneIsGone(pi: ExtensionAPI, paneId: string): Promise<boolean> {
	const probe = await runHerdr(pi, ["pane", "get", paneId], "pane get", () => null);
	if (probe.status !== "failed" || probe.exitCode !== 1) return false;
	try {
		return JSON.parse(probe.stderr || probe.stdout || "").error?.code === "pane_not_found";
	} catch {
		return false;
	}
}

/** Read notes before closing; daemon absence alone does not prove the TUI is dead. */
export async function drainOwnedReview(
	pi: ExtensionAPI,
	binary: HunkBinary,
	worktreeDir: string,
	live: HunkSession[],
): Promise<Drained> {
	const owned = ownedReview(worktreeDir);
	if (!owned) return { notes: [] };

	const registered = live.some((session) => session.sessionId === owned.sessionId);
	if (!registered && (await paneIsGone(pi, owned.paneId))) {
		forgetPane(worktreeDir);
		return { notes: [], lost: true };
	}

	// A failed poll can leave a live, annotated TUI with no captured id. Reuse
	// its launch baseline on retry rather than closing it as an empty pane.
	if (owned.sessionId === undefined && owned.beforeSessionIds !== undefined) {
		const discovered = discoverSession(live, new Set(owned.beforeSessionIds));
		if (discovered.ok && discovered.session) attachSession(worktreeDir, discovered.session.sessionId);
	}

	if (owned.sessionId === undefined || !live.some((session) => session.sessionId === owned.sessionId)) {
		return {
			notes: [],
			blocked: "could not identify the previous review; retry once hunk reconnects, or close its pane to abandon it",
		};
	}

	const read = await readUserNotes(pi, binary, owned.sessionId);
	if (!read.ok) return { notes: [], blocked: `could not read the previous review's notes (${read.reason})` };
	if (await closeAndForget(pi, worktreeDir, owned.paneId)) return { notes: read.notes };
	return { notes: read.notes, blocked: "could not close the previous review's pane" };
}
