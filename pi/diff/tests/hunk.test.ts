import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	detectHunk,
	type HunkAvailability,
	type HunkExec,
	type HunkSession,
	listHunkSessions,
	readUserNotes,
	type UserNote,
} from "#diff/hunk.ts";

interface ExecResult {
	code: number;
	stdout: string;
	stderr: string;
	killed: boolean;
}

interface ExecCall {
	command: string;
	args: string[];
	options?: { timeout?: number };
}

interface MockPi {
	execCalls: ExecCall[];
	exec: HunkExec["exec"];
}

const WORKTREE = "/worktrees/org/repo/wt/main";

function createMockPi(
	handler: (command: string, args: string[], options?: { timeout?: number }) => Promise<ExecResult> | ExecResult,
): MockPi {
	const execCalls: ExecCall[] = [];
	return {
		execCalls,
		async exec(command, args, options) {
			execCalls.push({ command, args, options });
			return await handler(command, args, options);
		},
	};
}

function okJson(json: string): ExecResult {
	return { code: 0, stdout: json, stderr: "", killed: false };
}

function fail(stdout: string, stderr = ""): ExecResult {
	return { code: 1, stdout, stderr, killed: false };
}

const NO_SESSION_STDOUT = "hunk: No active session matches repoRoot /worktrees/org/repo/wt/main.\n";

const SESSION_ID = "c142bb1b-8d91-4269-9463-d81bab9f8559";

// Recorded live from `hunk session list --json` (hunk 0.17.6). Fields the
// adapter ignores are kept so the parser is exercised against real output.
const SESSION_LIST_JSON = JSON.stringify({
	sessions: [
		{
			sessionId: "ac693860-1df2-4259-a2e7-67af689b0cd9",
			pid: 53751,
			cwd: WORKTREE,
			repoRoot: WORKTREE,
			launchedAt: "2026-07-27T15:38:01.368Z",
			terminal: { program: "ghostty", locations: [{ source: "tty", tty: "/dev/ttys004" }] },
			inputKind: "vcs",
			title: "wt/main origin/main",
			sourceLabel: WORKTREE,
			fileCount: 2,
			files: [],
		},
		{
			sessionId: SESSION_ID,
			pid: 26349,
			cwd: WORKTREE,
			repoRoot: WORKTREE,
			launchedAt: "2026-07-27T16:41:55.869Z",
			inputKind: "vcs",
			title: "wt/main 43e3afd6",
			fileCount: 21,
		},
		{
			sessionId: "99999999-0000-0000-0000-000000000000",
			repoRoot: "/some/other/repo",
			launchedAt: "2026-07-27T16:00:00.000Z",
		},
	],
});

const NO_NOTES_JSON = JSON.stringify({ comments: [] });

// Recorded live from `hunk session comment list --repo <path> --type user --json`
// on hunk 0.17.6; an ai note is included to prove the defensive source filter.
const MULTI_NOTE_JSON = JSON.stringify({
	comments: [
		{
			noteId: "user:1785163765618-1",
			source: "user",
			filePath: "pi/code-review/README.md",
			hunkIndex: 0,
			newRange: [45, 45],
			body: "hi",
			author: "user",
			createdAt: "2026-07-27T14:49:25.618Z",
			editable: true,
		},
		{
			noteId: "user:1785163765700-2",
			source: "user",
			filePath: "pi/diff/hunk.ts",
			hunkIndex: 1,
			newRange: [12, 18],
			body: "check the timeout here",
			author: "user",
			createdAt: "2026-07-27T14:50:00.000Z",
			editable: true,
		},
		{
			noteId: "user:1785163765800-3",
			source: "user",
			filePath: "README.md",
			oldRange: [3, 3],
			body: "no newRange on this one",
			author: "user",
			createdAt: "2026-07-27T14:51:00.000Z",
			editable: true,
		},
		{
			noteId: "ai:1785163765900-4",
			source: "ai",
			filePath: "src/app.ts",
			newRange: [10, 10],
			body: "agent rationale",
			author: "agent",
			createdAt: "2026-07-27T14:52:00.000Z",
			editable: false,
		},
	],
});

describe("detectHunk", () => {
	it("returns available when hunk --version exits 0", async () => {
		const pi = createMockPi(() => okJson("0.17.6\n"));
		const result = await detectHunk(pi);
		assert.deepEqual(result, { available: true } satisfies HunkAvailability);
		assert.deepEqual(pi.execCalls, [{ command: "hunk", args: ["--version"], options: { timeout: 4000 } }]);
	});

	it("returns an actionable unavailable result when exec throws (missing binary)", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const result = await detectHunk(pi);
		assert.equal(result.available, false);
		const message: string = result.available ? "" : result.message;
		assert.match(message, /not on PATH/);
		assert.match(message, /npm i -g hunkdiff/);
		assert.match(message, /brew install hunk/);
		assert.match(message, /Nix/);
	});

	it("returns unavailable on a nonzero exit", async () => {
		const pi = createMockPi(() => ({ code: 127, stdout: "", stderr: "command not found", killed: false }));
		const result = await detectHunk(pi);
		assert.equal(result.available, false);
		assert.match(result.available ? "" : result.message, /code 127/);
	});
});

describe("listHunkSessions", () => {
	it("returns nothing when no daemon or session is running", async () => {
		const pi = createMockPi(() => fail(NO_SESSION_STDOUT));
		assert.deepEqual(await listHunkSessions(pi, WORKTREE), []);
		assert.deepEqual(pi.execCalls[0]?.args, ["session", "list", "--json"]);
	});

	it("returns nothing when exec throws (no binary)", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		assert.deepEqual(await listHunkSessions(pi, WORKTREE), []);
	});

	it("returns every session for this worktree and excludes other repos", async () => {
		const pi = createMockPi(() => okJson(SESSION_LIST_JSON));
		const expected: HunkSession[] = [
			{ sessionId: "ac693860-1df2-4259-a2e7-67af689b0cd9", repoRoot: WORKTREE, launchedAt: "2026-07-27T15:38:01.368Z" },
			{ sessionId: "c142bb1b-8d91-4269-9463-d81bab9f8559", repoRoot: WORKTREE, launchedAt: "2026-07-27T16:41:55.869Z" },
		];
		assert.deepEqual(await listHunkSessions(pi, WORKTREE), expected);
	});

	it("returns nothing when stdout is JSON without a sessions array", async () => {
		const pi = createMockPi(() => okJson(JSON.stringify({ ok: true })));
		assert.deepEqual(await listHunkSessions(pi, WORKTREE), []);
	});
});

describe("readUserNotes", () => {
	it("addresses the session by id, never by repo", async () => {
		const pi = createMockPi(() => okJson(NO_NOTES_JSON));
		await readUserNotes(pi, SESSION_ID);
		assert.deepEqual(pi.execCalls[0]?.args, ["session", "comment", "list", SESSION_ID, "--type", "user", "--json"]);
	});

	it("reports a nonzero exit as a failure rather than as zero notes", async () => {
		const pi = createMockPi(() => ({
			code: 1,
			stdout: "",
			stderr: "hunk: Multiple active sessions match repoRoot /x; specify sessionId instead.\n",
			killed: false,
		}));
		const read = await readUserNotes(pi, SESSION_ID);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /Multiple active sessions/);
	});

	it("reports a thrown exec as a failure", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const read = await readUserNotes(pi, SESSION_ID);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /ENOENT/);
	});

	it("reports unparsable output as a failure, not emptiness", async () => {
		const pi = createMockPi(() => okJson("No active Hunk sessions.\n"));
		const read = await readUserNotes(pi, SESSION_ID);
		assert.equal(read.ok, false);
	});

	it("distinguishes a genuinely empty review from a failure", async () => {
		const pi = createMockPi(() => okJson(NO_NOTES_JSON));
		assert.deepEqual(await readUserNotes(pi, SESSION_ID), { ok: true, notes: [] });
	});

	it("keeps both anchor sides, drops ai notes, and never invents a range", async () => {
		const pi = createMockPi(() => okJson(MULTI_NOTE_JSON));
		const read = await readUserNotes(pi, SESSION_ID);
		assert.equal(read.ok, true);
		assert.deepEqual(read.ok ? read.notes : [], [
			{ filePath: "pi/code-review/README.md", newRange: [45, 45], body: "hi" },
			{ filePath: "pi/diff/hunk.ts", newRange: [12, 18], body: "check the timeout here" },
			// An old-side range is the only anchor a note on a deleted line has.
			{ filePath: "README.md", oldRange: [3, 3], body: "no newRange on this one" },
		] satisfies UserNote[]);
	});
});
