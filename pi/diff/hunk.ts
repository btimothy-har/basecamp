/**
 * A review uses one hunk executable even when the pane's shell has a different
 * PATH. Failed session and note reads must never imply emptiness: closing a
 * live review would destroy the only copy of the user's notes.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { resolveHunkExecutable } from "./hunk-executable.ts";

export type HunkExec = Pick<ExtensionAPI, "exec">;

type ExecResult = Awaited<ReturnType<HunkExec["exec"]>>;

const HUNK_TIMEOUT_MS = 4000;

const HUNK_INSTALL_HINT =
	"Install hunk to use /diff: `npm i -g hunkdiff`, `brew install hunk`, or add it via Nix (`hunk` on nixpkgs).";

export interface HunkBinary {
	executable: string;
	version: string;
}

export type HunkAvailability = { available: true; binary: HunkBinary } | { available: false; message: string };

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

export type HunkSessionRead = { ok: true; sessions: HunkSession[] } | { ok: false; reason: string };

export type UserNoteRead = { ok: true; notes: UserNote[] } | { ok: false; reason: string };

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isNumberPair(value: unknown): value is [number, number] {
	return Array.isArray(value) && value.length === 2 && typeof value[0] === "number" && typeof value[1] === "number";
}

function execFailure(result: ExecResult): string | null {
	const status = result.killed
		? `was killed or timed out (${HUNK_TIMEOUT_MS} ms limit)`
		: result.code !== 0
			? `exited with code ${result.code}`
			: null;
	if (!status) return null;
	const stderr = result.stderr.trim();
	return stderr ? `${status}: ${stderr}` : status;
}

function binaryLabel(binary: HunkBinary): string {
	return `${binary.executable} (${binary.version})`;
}

export async function detectHunk(pi: HunkExec, cwd: string): Promise<HunkAvailability> {
	const executable = await resolveHunkExecutable(process.env.PATH, cwd);
	if (!executable) return { available: false, message: `hunk is not on PATH. ${HUNK_INSTALL_HINT}` };
	try {
		const result = await pi.exec(executable, ["--version"], { cwd, timeout: HUNK_TIMEOUT_MS });
		const failure = execFailure(result);
		if (failure) return { available: false, message: `${executable} --version ${failure}` };
		const version = result.stdout.trim();
		if (!version) return { available: false, message: `${executable} --version returned no version` };
		return { available: true, binary: { executable, version } };
	} catch (err) {
		return { available: false, message: `${executable} --version failed: ${errorMessage(err)}` };
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
	if (!isObject(raw)) return null;
	const { sessionId, repoRoot, launchedAt } = raw;
	if (
		typeof sessionId !== "string" ||
		!sessionId.trim() ||
		typeof repoRoot !== "string" ||
		!repoRoot.trim() ||
		typeof launchedAt !== "string" ||
		!launchedAt.trim()
	) {
		return null;
	}
	return { sessionId, repoRoot, launchedAt };
}

/**
 * `hunk session list --json`, filtered to one worktree.
 *
 * Listing rather than `session get --repo` because hunk refuses a --repo that
 * matches more than one live session; enumerating stays unambiguous however
 * many are open, and lets a caller identify the one it just launched.
 */
export async function listHunkSessions(
	pi: HunkExec,
	binary: HunkBinary,
	worktreePath: string,
): Promise<HunkSessionRead> {
	let result: ExecResult;
	try {
		result = await pi.exec(binary.executable, ["session", "list", "--json"], { timeout: HUNK_TIMEOUT_MS });
	} catch (err) {
		return { ok: false, reason: errorMessage(err) };
	}
	const failure = execFailure(result);
	if (failure) return { ok: false, reason: failure };
	const parsed = parseJson(result.stdout);
	if (!isObject(parsed) || !Array.isArray(parsed.sessions)) {
		return { ok: false, reason: "returned no readable session list" };
	}
	const sessions: HunkSession[] = [];
	for (const [index, raw] of parsed.sessions.entries()) {
		const session = toSession(raw);
		if (!session) return { ok: false, reason: `returned an invalid session at index ${index}` };
		if (session.repoRoot === worktreePath) sessions.push(session);
	}
	return { ok: true, sessions };
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
export async function readUserNotes(pi: HunkExec, binary: HunkBinary, sessionId: string): Promise<UserNoteRead> {
	const context = `${binaryLabel(binary)} session comment list`;
	let result: ExecResult;
	try {
		result = await pi.exec(binary.executable, ["session", "comment", "list", sessionId, "--type", "user", "--json"], {
			timeout: HUNK_TIMEOUT_MS,
		});
	} catch (err) {
		return { ok: false, reason: `${context} failed: ${errorMessage(err)}` };
	}
	const failure = execFailure(result);
	if (failure) return { ok: false, reason: `${context} ${failure}` };
	const parsed = parseJson(result.stdout);
	if (!isObject(parsed) || !Array.isArray(parsed.comments)) {
		return { ok: false, reason: `${context} returned no readable comment list` };
	}
	const notes: UserNote[] = [];
	for (const raw of parsed.comments) {
		const note = toUserNote(raw);
		if (note) notes.push(note);
	}
	return { ok: true, notes };
}
