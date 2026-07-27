/**
 * Hunk CLI adapter — pure, typed wrappers over the `hunk` binary.
 *
 * Talks to hunk's local daemon via its session/comment subcommands. Nothing
 * here throws. Probes treat an absent binary, daemon, or session as an empty
 * result, but the note read is a discriminated result: after a review, "the
 * read failed" and "you wrote nothing" must never look alike, because notes
 * exist only in the TUI's memory and closing it destroys them. The exec
 * facility is passed in so callers and tests can substitute it.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";

export type HunkExec = Pick<ExtensionAPI, "exec">;

type ExecResult = Awaited<ReturnType<HunkExec["exec"]>>;

const HUNK_TIMEOUT_MS = 4000;

const HUNK_INSTALL_HINT =
	"Install hunk to use /diff: `npm i -g hunkdiff`, `brew install hunk`, or add it via Nix (`hunk` on nixpkgs).";

export type HunkAvailability = { available: true } | { available: false; message: string };

/** A live hunk session, reduced to what selecting and reporting one needs. */
export interface HunkSession {
	sessionId: string;
	repoRoot: string;
	launchedAt: string;
}

export interface UserNote {
	filePath: string;
	newRange?: [number, number];
	/** Set instead of newRange for a note left on a removed line. */
	oldRange?: [number, number];
	body: string;
}

export type UserNoteRead = { ok: true; notes: UserNote[] } | { ok: false; reason: string };

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isNumberPair(value: unknown): value is [number, number] {
	return Array.isArray(value) && value.length === 2 && typeof value[0] === "number" && typeof value[1] === "number";
}

/** `hunk --version` is the cheapest probe that fails fast when the binary is absent. */
export async function detectHunk(pi: HunkExec): Promise<HunkAvailability> {
	try {
		const result = await pi.exec("hunk", ["--version"], { timeout: HUNK_TIMEOUT_MS });
		if (result.code === 0) return { available: true };
		return { available: false, message: `hunk exited with code ${result.code}. ${HUNK_INSTALL_HINT}` };
	} catch (err) {
		return { available: false, message: `hunk is not on PATH: ${errorMessage(err)}. ${HUNK_INSTALL_HINT}` };
	}
}

function parseJson(stdout: string): unknown {
	const trimmed = stdout.trim();
	if (trimmed === "") return null;
	try {
		return JSON.parse(trimmed);
	} catch {
		return null;
	}
}

function toSession(raw: unknown): HunkSession | null {
	if (!isObject(raw) || typeof raw.sessionId !== "string") return null;
	return {
		sessionId: raw.sessionId,
		repoRoot: typeof raw.repoRoot === "string" ? raw.repoRoot : "",
		launchedAt: typeof raw.launchedAt === "string" ? raw.launchedAt : "",
	};
}

/**
 * `hunk session list --json`, filtered to one worktree.
 *
 * Listing rather than `session get --repo` because hunk refuses a --repo that
 * matches more than one live session; enumerating stays unambiguous however
 * many are open, and lets a caller identify the one it just launched.
 */
export async function listHunkSessions(pi: HunkExec, worktreePath: string): Promise<HunkSession[]> {
	let result: ExecResult;
	try {
		result = await pi.exec("hunk", ["session", "list", "--json"], { timeout: HUNK_TIMEOUT_MS });
	} catch {
		return [];
	}
	if (result.code !== 0) return [];
	const parsed = parseJson(result.stdout);
	if (!isObject(parsed) || !Array.isArray(parsed.sessions)) return [];
	const sessions: HunkSession[] = [];
	for (const raw of parsed.sessions) {
		const session = toSession(raw);
		if (session && session.repoRoot === worktreePath) sessions.push(session);
	}
	return sessions;
}

function toUserNote(raw: unknown): UserNote | null {
	if (!isObject(raw) || raw.source !== "user") return null;
	const { filePath, body } = raw;
	if (typeof filePath !== "string" || typeof body !== "string") return null;
	const note: UserNote = { filePath, body };
	if (isNumberPair(raw.newRange)) note.newRange = raw.newRange;
	// A note on a deleted line carries only oldRange; without it the anchor is lost.
	if (isNumberPair(raw.oldRange)) note.oldRange = raw.oldRange;
	return note;
}

/**
 * `hunk session comment list <sessionId> --type user --json`.
 *
 * Addressed by session id, never by --repo: a second session on the same root
 * makes --repo ambiguous and hunk exits non-zero. Every failure is reported
 * rather than flattened to zero notes, so a caller can keep the window open
 * instead of destroying the only copy of the user's review.
 *
 * `--type user` filters server-side; the `source` check guards shape drift.
 */
export async function readUserNotes(pi: HunkExec, sessionId: string): Promise<UserNoteRead> {
	let result: ExecResult;
	try {
		result = await pi.exec("hunk", ["session", "comment", "list", sessionId, "--type", "user", "--json"], {
			timeout: HUNK_TIMEOUT_MS,
		});
	} catch (err) {
		return { ok: false, reason: errorMessage(err) };
	}
	if (result.code !== 0) {
		return { ok: false, reason: result.stderr.trim() || `hunk exited with code ${result.code}` };
	}
	const parsed = parseJson(result.stdout);
	if (!isObject(parsed) || !Array.isArray(parsed.comments)) {
		return { ok: false, reason: "hunk returned no readable comment list" };
	}
	const notes: UserNote[] = [];
	for (const raw of parsed.comments) {
		const note = toUserNote(raw);
		if (note) notes.push(note);
	}
	return { ok: true, notes };
}
