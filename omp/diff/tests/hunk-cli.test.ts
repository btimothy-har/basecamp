import { describe, expect, test } from "bun:test";
import type { ExecOptions, ExecResult } from "@oh-my-pi/pi-coding-agent";
import { type HunkBinary, type HunkExec, listHunkSessions, readUserNotes, type UserNote } from "../hunk-cli.ts";

const WORKTREE = "/worktrees/org/repo/wt/main";
const BINARY: HunkBinary = { executable: "/bin with 'quotes;$()/hunk", version: "0.21.1" };
const SESSION_ID = "c142bb1b-8d91-4269-9463-d81bab9f8559";

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

function mockPi(handler: (command: string, args: string[]) => ExecResult): { pi: HunkExec; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi: HunkExec = {
		exec: (command: string, args: string[], options?: ExecOptions) => {
			calls.push({ command, args, options });
			return Promise.resolve(handler(command, args));
		},
	};
	return { pi, calls };
}

function ok(stdout: string): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

function fail(stdout: string, stderr = ""): ExecResult {
	return { code: 1, stdout, stderr, killed: false };
}

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
		{ sessionId: SESSION_ID, pid: 26349, cwd: WORKTREE, repoRoot: WORKTREE, launchedAt: "2026-07-27T16:41:55.869Z" },
		{
			sessionId: "99999999-0000-0000-0000-000000000000",
			repoRoot: "/some/other/repo",
			pid: 10001,
			launchedAt: "2026-07-27T16:00:00Z",
		},
	],
});

// Recorded live from `hunk session comment list --type user --json`; an ai
// note is included to prove the defensive source filter.
const MULTI_NOTE_JSON = JSON.stringify({
	comments: [
		{
			noteId: "user:1785163765618-1",
			source: "user",
			filePath: "omp/review/README.md",
			hunkIndex: 0,
			newRange: [45, 45],
			body: "hi",
			author: "user",
			editable: true,
		},
		{
			noteId: "user:1785163765700-2",
			source: "user",
			filePath: "omp/diff/hunk-cli.ts",
			newRange: [12, 18],
			body: "check the timeout here",
			author: "user",
		},
		{ noteId: "user:1785163765800-3", source: "user", filePath: "README.md", oldRange: [3, 3], body: "removed line" },
		{
			noteId: "user:1785163765850-4",
			source: "user",
			filePath: "src/mixed.ts",
			oldRange: [4, 5],
			newRange: [4, 6],
			body: "two-sided selection",
		},
		{ noteId: "ai:1785163765900-4", source: "ai", filePath: "src/app.ts", newRange: [10, 10], body: "agent rationale" },
	],
});

describe("listHunkSessions", () => {
	test("returns every session for this worktree and excludes other repos", async () => {
		const { pi, calls } = mockPi(() => ok(SESSION_LIST_JSON));
		expect(await listHunkSessions(pi, BINARY, WORKTREE)).toEqual({
			ok: true,
			sessions: [
				{
					sessionId: "ac693860-1df2-4259-a2e7-67af689b0cd9",
					pid: 53751,
					repoRoot: WORKTREE,
					launchedAt: "2026-07-27T15:38:01.368Z",
				},
				{ sessionId: SESSION_ID, pid: 26349, repoRoot: WORKTREE, launchedAt: "2026-07-27T16:41:55.869Z" },
			],
		});
		expect(calls).toEqual([
			{ command: BINARY.executable, args: ["session", "list", "--json"], options: { timeout: 4000 } },
		]);
	});

	test("preserves nonzero exit status and stderr instead of implying no sessions", async () => {
		const stderr = "error: unknown command 'list'\nrequired support: session list\n";
		const { pi } = mockPi(() => fail("", stderr));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		expect(read).toEqual({ ok: false, reason: `exited with code 1: ${stderr.trim()}` });
	});

	test("rejects killed or timed-out output even when code is zero and JSON looks valid", async () => {
		const { pi } = mockPi(() => ({ ...ok(SESSION_LIST_JSON), killed: true, stderr: "deadline exceeded" }));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		expect(read).toEqual({ ok: false, reason: "was killed or timed out (4000 ms limit): deadline exceeded" });
	});

	test("reports a thrown exec without retrying", async () => {
		const { pi, calls } = mockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		expect(await listHunkSessions(pi, BINARY, WORKTREE)).toEqual({ ok: false, reason: "spawn hunk ENOENT" });
		expect(calls).toHaveLength(1);
	});

	for (const stdout of ["", "not json", "null", "[]", '{"ok":true}', '{"sessions":null}']) {
		test(`reports malformed session-list output ${JSON.stringify(stdout)}`, async () => {
			const { pi } = mockPi(() => ok(stdout));
			expect(await listHunkSessions(pi, BINARY, WORKTREE)).toEqual({
				ok: false,
				reason: "returned no readable session list",
			});
		});
	}

	test("distinguishes a genuinely empty list from failure", async () => {
		const { pi } = mockPi(() => ok('{"sessions":[]}'));
		expect(await listHunkSessions(pi, BINARY, WORKTREE)).toEqual({ ok: true, sessions: [] });
	});

	test("fails the whole list rather than dropping an invalid session", async () => {
		const payload = JSON.parse(SESSION_LIST_JSON) as { sessions: unknown[] };
		payload.sessions.push({ sessionId: "", repoRoot: WORKTREE, launchedAt: "2026-07-27T16:00:00Z" });
		const { pi } = mockPi(() => ok(JSON.stringify(payload)));
		expect(await listHunkSessions(pi, BINARY, WORKTREE)).toEqual({
			ok: false,
			reason: "returned an invalid session at index 3",
		});
	});

	test("keeps pid-less sessions in an unfiltered baseline without treating them as invalid", async () => {
		const payload = {
			sessions: [{ sessionId: "legacy-session", launchedAt: "2026-09-10T06:00:00Z" }],
		};
		const { pi } = mockPi(() => ok(JSON.stringify(payload)));

		expect(await listHunkSessions(pi, BINARY)).toEqual({
			ok: true,
			sessions: [{ sessionId: "legacy-session", launchedAt: "2026-09-10T06:00:00Z" }],
		});
	});

	test("ignores non-VCS sessions whose registration legitimately omits repoRoot", async () => {
		const payload = JSON.parse(SESSION_LIST_JSON) as { sessions: unknown[] };
		payload.sessions.push({
			sessionId: "patch-session",
			pid: 31415,
			inputKind: "patch",
			launchedAt: "2026-09-10T06:00:00Z",
		});
		const { pi } = mockPi(() => ok(JSON.stringify(payload)));
		const read = await listHunkSessions(pi, BINARY, WORKTREE);
		expect(read.ok && read.sessions.length).toBe(2);
	});
});

describe("readUserNotes", () => {
	test("addresses the session by id, never by repo", async () => {
		const { pi, calls } = mockPi(() => ok('{"comments":[]}'));
		await readUserNotes(pi, BINARY, SESSION_ID);
		expect(calls).toEqual([
			{
				command: BINARY.executable,
				args: ["session", "comment", "list", SESSION_ID, "--type", "user", "--json"],
				options: { timeout: 4000 },
			},
		]);
	});

	test("reports a nonzero exit as a failure rather than as zero notes", async () => {
		const { pi } = mockPi(() => fail("", "hunk: daemon gone\n"));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		expect(read.ok).toBe(false);
		if (!read.ok) expect(read.reason).toContain("daemon gone");
	});

	test("reports killed reads even when their output is a valid empty review", async () => {
		const { pi } = mockPi(() => ({ ...ok('{"comments":[]}'), killed: true }));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		expect(read.ok).toBe(false);
		if (!read.ok) expect(read.reason).toMatch(/0\.21\.1.*killed or timed out/);
	});

	test("reports unparsable output as a failure, not emptiness", async () => {
		const { pi } = mockPi(() => ok("No active Hunk sessions.\n"));
		expect((await readUserNotes(pi, BINARY, SESSION_ID)).ok).toBe(false);
	});

	test("distinguishes a genuinely empty review from a failure", async () => {
		const { pi } = mockPi(() => ok('{"comments":[]}'));
		expect(await readUserNotes(pi, BINARY, SESSION_ID)).toEqual({ ok: true, notes: [] });
	});

	test("keeps both anchor sides, drops ai notes, and never invents a range", async () => {
		const { pi } = mockPi(() => ok(MULTI_NOTE_JSON));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		expect(read.ok ? read.notes : []).toEqual([
			{ filePath: "omp/review/README.md", newRange: [45, 45], body: "hi" },
			{ filePath: "omp/diff/hunk-cli.ts", newRange: [12, 18], body: "check the timeout here" },
			// An old-side range is the only anchor a note on a deleted line has.
			{ filePath: "README.md", oldRange: [3, 3], body: "removed line" },
			{ filePath: "src/mixed.ts", oldRange: [4, 5], newRange: [4, 6], body: "two-sided selection" },
		] satisfies UserNote[]);
	});

	test("fails the whole read when a user note has an invalid range", async () => {
		const malformed = JSON.stringify({
			comments: [{ source: "user", filePath: "src/a.ts", newRange: [7, 3], body: "broken" }],
		});
		const { pi } = mockPi(() => ok(malformed));
		const read = await readUserNotes(pi, BINARY, SESSION_ID);
		expect(read.ok).toBe(false);
		if (!read.ok) expect(read.reason).toContain("returned an invalid user comment at index 0");
	});
});
