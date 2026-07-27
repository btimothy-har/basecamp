/**
 * Hunk CLI adapter — pure, typed wrappers over the `hunk` binary.
 *
 * Talks to hunk's local daemon via its session/comment subcommands. Absent
 * binary, absent daemon, and absent session are all normal empty results,
 * never exceptions. The exec facility is passed in so callers (and tests) can
 * substitute it without a real `hunk` on PATH.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";

export type HunkExec = Pick<ExtensionAPI, "exec">;

type ExecResult = Awaited<ReturnType<HunkExec["exec"]>>;

const HUNK_TIMEOUT_MS = 4000;

const HUNK_INSTALL_HINT =
	"Install hunk to use /diff: `npm i -g hunkdiff`, `brew install hunk`, or add it via Nix (`hunk` on nixpkgs).";

export type HunkAvailability = { available: true } | { available: false; message: string };

/** A live hunk session for a worktree. Fields beyond identity are omitted. */
export interface HunkSession {
	sessionId: string;
	repoRoot: string;
	cwd: string;
	title: string;
	launchedAt: string;
	fileCount: number;
}

export type HunkSessionLookup = { found: true; session: HunkSession } | { found: false };

export interface UserNote {
	filePath: string;
	newRange?: [number, number];
	body: string;
}

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
	if (!isObject(raw) || !isObject(raw.session)) return null;
	const s = raw.session;
	const { sessionId, repoRoot, cwd, title, launchedAt, fileCount } = s;
	if (typeof sessionId !== "string") return null;
	return {
		sessionId,
		repoRoot: typeof repoRoot === "string" ? repoRoot : "",
		cwd: typeof cwd === "string" ? cwd : "",
		title: typeof title === "string" ? title : "",
		launchedAt: typeof launchedAt === "string" ? launchedAt : "",
		fileCount: typeof fileCount === "number" ? fileCount : 0,
	};
}

/**
 * `hunk session get --repo <path> --json`. A non-zero exit or non-JSON output
 * (no daemon running, no session for this repo) is "no session", not an error.
 */
export async function getHunkSession(pi: HunkExec, worktreePath: string): Promise<HunkSessionLookup> {
	let result: ExecResult;
	try {
		result = await pi.exec("hunk", ["session", "get", "--repo", worktreePath, "--json"], {
			timeout: HUNK_TIMEOUT_MS,
		});
	} catch {
		return { found: false };
	}
	if (result.code !== 0) return { found: false };
	const session = toSession(parseJson(result.stdout));
	return session ? { found: true, session } : { found: false };
}

function toUserNote(raw: unknown): UserNote | null {
	if (!isObject(raw) || raw.source !== "user") return null;
	const { filePath, body } = raw;
	if (typeof filePath !== "string" || typeof body !== "string") return null;
	const note: UserNote = { filePath, body };
	if (isNumberPair(raw.newRange)) note.newRange = raw.newRange;
	return note;
}

/**
 * `hunk session comment list --repo <path> --type user --json`. Absent daemon,
 * absent session, zero notes, and unparseable output all yield an empty array.
 * `--type user` already filters server-side; the `source === "user"` check is a
 * defensive guard against shape drift.
 */
export async function readUserNotes(pi: HunkExec, worktreePath: string): Promise<UserNote[]> {
	let result: ExecResult;
	try {
		result = await pi.exec("hunk", ["session", "comment", "list", "--repo", worktreePath, "--type", "user", "--json"], {
			timeout: HUNK_TIMEOUT_MS,
		});
	} catch {
		return [];
	}
	if (result.code !== 0) return [];
	const parsed = parseJson(result.stdout);
	if (!isObject(parsed) || !Array.isArray(parsed.comments)) return [];
	const notes: UserNote[] = [];
	for (const raw of parsed.comments) {
		const note = toUserNote(raw);
		if (note) notes.push(note);
	}
	return notes;
}
