import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	type HunkBinary,
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
const BINARY: HunkBinary = { executable: "/bin with 'quotes;$()/hunk", version: "0.21.1" };

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

describe("listHunkSessions", () => {
	it("preserves nonzero exit status and stderr instead of implying no sessions", async () => {
		const stderr = "error: unknown command 'list'\nrequired support: session list\n";
		const pi = createMockPi(() => fail(NO_SESSION_STDOUT, stderr));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		assert.equal(read.ok, false);
		assert.equal(read.ok ? "" : read.reason, `exited with code 1: ${stderr.trim()}`);
		assert.deepEqual(pi.execCalls, [
			{ command: BINARY.executable, args: ["session", "list", "--json"], options: { timeout: 4000 } },
		]);
	});

	it("reports an exit code even without stderr", async () => {
		const pi = createMockPi(() => fail(""));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /exited with code 1/);
	});

	it("reports thrown exec errors without retrying or changing binaries", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		assert.equal(read.ok, false);
		assert.equal(read.ok ? "" : read.reason, "spawn hunk ENOENT");
		assert.equal(pi.execCalls.length, 1);
	});

	it("rejects killed or timed-out output even when code is zero and JSON looks valid", async () => {
		const pi = createMockPi(() => ({ ...okJson(SESSION_LIST_JSON), killed: true, stderr: "deadline exceeded" }));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		assert.equal(read.ok, false);
		assert.equal(read.ok ? "" : read.reason, "was killed or timed out (4000 ms limit): deadline exceeded");
	});

	it("returns every session for this worktree and excludes other repos", async () => {
		const pi = createMockPi(() => okJson(SESSION_LIST_JSON));
		const expected: HunkSession[] = [
			{ sessionId: "ac693860-1df2-4259-a2e7-67af689b0cd9", repoRoot: WORKTREE, launchedAt: "2026-07-27T15:38:01.368Z" },
			{ sessionId: "c142bb1b-8d91-4269-9463-d81bab9f8559", repoRoot: WORKTREE, launchedAt: "2026-07-27T16:41:55.869Z" },
		];
		assert.deepEqual(await listHunkSessions(pi, BINARY, WORKTREE), { ok: true, sessions: expected });
	});

	for (const stdout of ["", "not json", "null", "[]", '{"ok":true}', '{"sessions":null}']) {
		it(`reports malformed session-list output ${JSON.stringify(stdout)}`, async () => {
			const pi = createMockPi(() => okJson(stdout));
			const read = await listHunkSessions(pi, BINARY, WORKTREE);
			assert.equal(read.ok, false);
			assert.equal(read.ok ? "" : read.reason, "returned no readable session list");
		});
	}

	it("distinguishes a genuinely empty list from failure", async () => {
		const pi = createMockPi(() => okJson('{"sessions":[]}'));
		assert.deepEqual(await listHunkSessions(pi, BINARY, WORKTREE), { ok: true, sessions: [] });
	});

	it("returns a successful empty result when valid sessions belong to other worktrees", async () => {
		const pi = createMockPi(() => okJson(SESSION_LIST_JSON));
		assert.deepEqual(await listHunkSessions(pi, BINARY, "/other/worktree"), { ok: true, sessions: [] });
	});

	const session = { sessionId: SESSION_ID, repoRoot: WORKTREE, launchedAt: "2026-07-27T16:00:00.000Z" };
	const invalidSessions = [
		null,
		[],
		{},
		{ ...session, sessionId: "" },
		{ ...session, sessionId: 42 },
		{ ...session, repoRoot: undefined },
		{ ...session, repoRoot: 42 },
		{ ...session, repoRoot: " " },
		{ ...session, launchedAt: undefined },
		{ ...session, launchedAt: 42 },
		{ ...session, launchedAt: "" },
	];
	for (const invalid of invalidSessions) {
		it(`rejects the whole list rather than dropping an invalid session ${JSON.stringify(invalid)}`, async () => {
			const pi = createMockPi(() => okJson(JSON.stringify({ sessions: [session, invalid] })));
			const read = await listHunkSessions(pi, BINARY, WORKTREE);
			assert.equal(read.ok, false);
			assert.equal(read.ok ? "" : read.reason, "returned an invalid session at index 1");
		});
	}
});

describe("readUserNotes", () => {
	it("addresses the session by id, never by repo", async () => {
		const pi = createMockPi(() => okJson(NO_NOTES_JSON));
		await readUserNotes(pi, BINARY, SESSION_ID);
		assert.deepEqual(pi.execCalls, [
			{
				command: BINARY.executable,
				args: ["session", "comment", "list", SESSION_ID, "--type", "user", "--json"],
				options: { timeout: 4000 },
			},
		]);
	});

	it("reports a nonzero exit as a failure rather than as zero notes", async () => {
		const pi = createMockPi(() => ({
			code: 1,
			stdout: "",
			stderr: "hunk: Multiple active sessions match repoRoot /x; specify sessionId instead.\n",
			killed: false,
		}));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /Multiple active sessions/);
	});

	it("reports a thrown exec as a failure", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /ENOENT/);
	});

	it("reports killed reads even when their output is a valid empty review", async () => {
		const pi = createMockPi(() => ({ ...okJson(NO_NOTES_JSON), killed: true }));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		assert.equal(read.ok, false);
		assert.match(read.ok ? "" : read.reason, /0\.21\.1.*killed or timed out/);
	});

	it("reports unparsable output as a failure, not emptiness", async () => {
		const pi = createMockPi(() => okJson("No active Hunk sessions.\n"));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		assert.equal(read.ok, false);
	});

	it("distinguishes a genuinely empty review from a failure", async () => {
		const pi = createMockPi(() => okJson(NO_NOTES_JSON));
		assert.deepEqual(await readUserNotes(pi, BINARY, SESSION_ID), { ok: true, notes: [] });
	});

	it("keeps both anchor sides, drops ai notes, and never invents a range", async () => {
		const pi = createMockPi(() => okJson(MULTI_NOTE_JSON));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		assert.equal(read.ok, true);
		assert.deepEqual(read.ok ? read.notes : [], [
			{ filePath: "pi/code-review/README.md", newRange: [45, 45], body: "hi" },
			{ filePath: "pi/diff/hunk.ts", newRange: [12, 18], body: "check the timeout here" },
			// An old-side range is the only anchor a note on a deleted line has.
			{ filePath: "README.md", oldRange: [3, 3], body: "no newRange on this one" },
		] satisfies UserNote[]);
	});
});
