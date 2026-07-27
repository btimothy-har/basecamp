import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	detectHunk,
	getHunkSession,
	type HunkAvailability,
	type HunkExec,
	type HunkSession,
	readUserNotes,
	type UserNote,
} from "../hunk.ts";

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

const SESSION_JSON = JSON.stringify({
	session: {
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
		snapshot: { updatedAt: "2026-07-27T15:38:01.455Z", state: {} },
	},
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

describe("getHunkSession", () => {
	it("returns found:false when no daemon/session is running (nonzero, non-JSON)", async () => {
		const pi = createMockPi(() => fail(NO_SESSION_STDOUT));
		const result = await getHunkSession(pi, WORKTREE);
		assert.deepEqual(result, { found: false });
		assert.deepEqual(pi.execCalls[0]?.args, ["session", "get", "--repo", WORKTREE, "--json"]);
	});

	it("returns found:false when exec throws (no binary)", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const result = await getHunkSession(pi, WORKTREE);
		assert.deepEqual(result, { found: false });
	});

	it("returns the session when one is live", async () => {
		const pi = createMockPi(() => okJson(SESSION_JSON));
		const result = await getHunkSession(pi, WORKTREE);
		assert.equal(result.found, true);
		if (!result.found) return;
		const expected: HunkSession = {
			sessionId: "ac693860-1df2-4259-a2e7-67af689b0cd9",
			repoRoot: WORKTREE,
			cwd: WORKTREE,
			title: "wt/main origin/main",
			launchedAt: "2026-07-27T15:38:01.368Z",
			fileCount: 2,
		};
		assert.deepEqual(result.session, expected);
	});

	it("returns found:false when stdout is JSON without a session envelope", async () => {
		const pi = createMockPi(() => okJson(JSON.stringify({ ok: true })));
		const result = await getHunkSession(pi, WORKTREE);
		assert.deepEqual(result, { found: false });
	});
});

describe("readUserNotes", () => {
	it("returns an empty array when no session is running (nonzero, non-JSON)", async () => {
		const pi = createMockPi(() => fail(NO_SESSION_STDOUT));
		const notes = await readUserNotes(pi, WORKTREE);
		assert.deepEqual(notes, []);
		assert.deepEqual(pi.execCalls[0]?.args, [
			"session",
			"comment",
			"list",
			"--repo",
			WORKTREE,
			"--type",
			"user",
			"--json",
		]);
	});

	it("returns an empty array when exec throws (no binary)", async () => {
		const pi = createMockPi(() => {
			throw new Error("spawn hunk ENOENT");
		});
		const notes = await readUserNotes(pi, WORKTREE);
		assert.deepEqual(notes, []);
	});

	it("returns an empty array for a live session with zero user notes", async () => {
		const pi = createMockPi(() => okJson(NO_NOTES_JSON));
		const notes = await readUserNotes(pi, WORKTREE);
		assert.deepEqual(notes, [] satisfies UserNote[]);
	});

	it("returns only user notes, carrying newRange values, and drops ai notes", async () => {
		const pi = createMockPi(() => okJson(MULTI_NOTE_JSON));
		const notes = await readUserNotes(pi, WORKTREE);
		assert.deepEqual(notes, [
			{ filePath: "pi/code-review/README.md", newRange: [45, 45], body: "hi" },
			{ filePath: "pi/diff/hunk.ts", newRange: [12, 18], body: "check the timeout here" },
			{ filePath: "README.md", body: "no newRange on this one" },
		] satisfies UserNote[]);
	});

	it("returns an empty array when stdout is not JSON", async () => {
		const pi = createMockPi(() => okJson("No active Hunk sessions.\n"));
		const notes = await readUserNotes(pi, WORKTREE);
		assert.deepEqual(notes, []);
	});
});
