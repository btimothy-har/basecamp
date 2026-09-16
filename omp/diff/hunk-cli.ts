/**
 * Hunk CLI adapter for transactional /diff. Pins one absolute executable so a
 * pane shell with a different PATH still runs the binary that was validated,
 * lists sessions as strict JSON, identifies the one session a launch
 * registered, and reads user notes by exact session id.
 *
 * A failed session or note read is never reported as empty: hunk keeps notes
 * in memory, so flattening a failure would destroy the only copy of the
 * user's review.
 */

import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import { delimiter, resolve } from "node:path";
import type { ExecResult, ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

export type HunkExec = Pick<ExtensionAPI, "exec">;

export const HUNK_TIMEOUT_MS = 4000;

const HUNK_INSTALL_HINT =
	"Install hunk to use /diff: `npm i -g hunkdiff`, `brew install hunk`, or add it via Nix (`hunk` on nixpkgs).";

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export interface HunkBinary {
	executable: string;
	version: string;
}

export type HunkAvailability = { available: true; binary: HunkBinary } | { available: false; message: string };

/** A live hunk session, reduced to what selecting and reporting one needs. */
export interface HunkSession {
	sessionId: string;
	pid?: number;
	/** Non-VCS inputs such as patch files have no repository root. */
	repoRoot?: string;
	launchedAt: string;
}

export interface UserNote {
	filePath: string;
	newRange?: [number, number];
	/** Old-side range; two-sided selections may also carry newRange. */
	oldRange?: [number, number];
	body: string;
}

export type HunkSessionRead = { ok: true; sessions: HunkSession[] } | { ok: false; reason: string };

export type UserNoteRead = { ok: true; notes: UserNote[] } | { ok: false; reason: string };

export interface LaunchPoll {
	attempts: number;
	intervalMs: number;
}

export type SessionDiscovery = { ok: true; session: HunkSession | null } | { ok: false; reason: string };
export type HunkPidSource = ReadonlySet<number> | (() => Promise<ReadonlySet<number>>);

/**
 * The first executable `hunk` on PATH, as an absolute path rooted at cwd.
 * Missing or inaccessible candidates do not shadow later executable PATH
 * entries. The PATH pathname is preserved rather than resolved: following a
 * launcher symlink can change its behavior.
 */
export async function resolveHunkExecutable(path: string | undefined, cwd: string): Promise<string | null> {
	if (path === undefined) return null;
	for (const directory of path.split(delimiter)) {
		const candidate = resolve(cwd, directory, "hunk");
		try {
			if (!(await stat(candidate)).isFile()) continue;
			await access(candidate, constants.X_OK);
			return candidate;
		} catch {}
	}
	return null;
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

function execOptions(cwd?: string): { cwd?: string; timeout: number } {
	return cwd ? { cwd, timeout: HUNK_TIMEOUT_MS } : { timeout: HUNK_TIMEOUT_MS };
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

		const help = await pi.exec(executable, ["patch", "--help"], { cwd, timeout: HUNK_TIMEOUT_MS });
		const helpFailure = execFailure(help);
		if (helpFailure) return { available: false, message: `${executable} patch --help ${helpFailure}` };
		if (!help.stdout.includes("--agent-context") || !help.stdout.includes("--agent-notes")) {
			return {
				available: false,
				message: `${executable} (${version}) lacks the patch-mode agent-note support /diff requires`,
			};
		}
		return { available: true, binary: { executable, version } };
	} catch (err) {
		return { available: false, message: `${executable} capability probe failed: ${errorMessage(err)}` };
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

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isLineRange(value: unknown): value is [number, number] {
	return (
		Array.isArray(value) &&
		value.length === 2 &&
		Number.isInteger(value[0]) &&
		Number.isInteger(value[1]) &&
		value[0] >= 1 &&
		value[1] >= value[0]
	);
}

function toSession(raw: unknown): HunkSession | null {
	if (!isObject(raw)) return null;
	const { sessionId, pid, repoRoot, launchedAt } = raw;
	if (
		typeof sessionId !== "string" ||
		!sessionId.trim() ||
		(pid !== undefined && (!Number.isInteger(pid) || (pid as number) < 1)) ||
		(repoRoot !== undefined && (typeof repoRoot !== "string" || !repoRoot.trim())) ||
		typeof launchedAt !== "string" ||
		!launchedAt.trim()
	) {
		return null;
	}
	const session: HunkSession = { sessionId, launchedAt };
	if (pid !== undefined) session.pid = pid as number;
	if (repoRoot !== undefined) session.repoRoot = repoRoot;
	return session;
}

/**
 * `hunk session list --json`, optionally filtered to one worktree.
 *
 * Omitting `worktreePath` is required for frozen patch sessions, which carry
 * no repoRoot. Callers then bind the fresh session to the launched Herdr pane
 * by PID. A missing PID remains readable for baseline accounting but cannot
 * satisfy that binding; other malformed session shapes fail the whole list.
 */
export async function listHunkSessions(
	pi: HunkExec,
	binary: HunkBinary,
	worktreePath?: string,
	cwd?: string,
): Promise<HunkSessionRead> {
	let result: ExecResult;
	try {
		result = await pi.exec(binary.executable, ["session", "list", "--json"], execOptions(cwd));
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
		if (worktreePath === undefined || session.repoRoot === worktreePath) sessions.push(session);
	}
	return { ok: true, sessions };
}

function toUserNote(raw: unknown): UserNote | "ignore" | null {
	if (!isObject(raw)) return null;
	if (raw.source !== "user") return "ignore";
	const { filePath, body } = raw;
	if (typeof filePath !== "string" || typeof body !== "string") return null;
	if (raw.newRange !== undefined && !isLineRange(raw.newRange)) return null;
	if (raw.oldRange !== undefined && !isLineRange(raw.oldRange)) return null;
	const note: UserNote = { filePath, body };
	if (raw.newRange !== undefined) note.newRange = raw.newRange as [number, number];
	if (raw.oldRange !== undefined) note.oldRange = raw.oldRange as [number, number];
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
export async function readUserNotes(
	pi: HunkExec,
	binary: HunkBinary,
	sessionId: string,
	cwd?: string,
): Promise<UserNoteRead> {
	const context = `${binary.executable} (${binary.version}) session comment list`;
	let result: ExecResult;
	try {
		result = await pi.exec(
			binary.executable,
			["session", "comment", "list", sessionId, "--type", "user", "--json"],
			execOptions(cwd),
		);
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
	for (const [index, raw] of parsed.comments.entries()) {
		const note = toUserNote(raw);
		if (note === null) {
			return { ok: false, reason: `${context} returned an invalid user comment at index ${index}` };
		}
		if (note !== "ignore") notes.push(note);
	}
	return { ok: true, notes };
}

/**
 * The session launched in one Herdr pane, identified against the baseline and
 * the pane's foreground process IDs. More than one matching session is
 * ambiguous, so discovery fails rather than reading another review's notes.
 */
export function discoverNewSession(
	live: HunkSession[],
	before: ReadonlySet<string>,
	expectedPids?: ReadonlySet<number>,
): SessionDiscovery {
	const fresh = live.filter(
		(session) =>
			!before.has(session.sessionId) &&
			(expectedPids === undefined || (session.pid !== undefined && expectedPids.has(session.pid))),
	);
	if (fresh.length > 1) {
		return {
			ok: false,
			reason: "multiple new hunk sessions appeared in the launched pane; cannot identify this review",
		};
	}
	return { ok: true, session: fresh[0] ?? null };
}

/**
 * Poll for the launched session. A shell accepting the launch command does
 * not prove hunk registered, and a cold daemon may accept connections before
 * its health endpoint is ready, so a failed poll is retried rather than
 * reported; the last failure is returned only once the poll budget is spent.
 */
export async function awaitLaunchedSession(
	pi: HunkExec,
	binary: HunkBinary,
	worktreePath: string | undefined,
	before: ReadonlySet<string>,
	poll: LaunchPoll,
	sleep: (ms: number) => Promise<void> = (ms) => {
		const { promise, resolve: wake } = Promise.withResolvers<void>();
		setTimeout(wake, ms);
		return promise;
	},
	expectedPids?: HunkPidSource,
	cwd?: string,
): Promise<SessionDiscovery> {
	let lastAttempt: SessionDiscovery = { ok: true, session: null };
	for (let attempt = 0; attempt < poll.attempts; attempt++) {
		await sleep(poll.intervalMs);
		let currentPids: ReadonlySet<number> | undefined;
		try {
			currentPids = typeof expectedPids === "function" ? await expectedPids() : expectedPids;
		} catch (error) {
			lastAttempt = { ok: false, reason: errorMessage(error) };
			continue;
		}
		const read = await listHunkSessions(pi, binary, worktreePath, cwd);
		if (!read.ok) {
			lastAttempt = read;
			continue;
		}
		lastAttempt = discoverNewSession(read.sessions, before, currentPids);
		if (!lastAttempt.ok || lastAttempt.session) return lastAttempt;
	}
	return lastAttempt;
}
