import { describe, expect, test } from "bun:test";
import type { ExecOptions, ExecResult } from "@oh-my-pi/pi-coding-agent";
import {
	awaitLaunchedSession,
	discoverNewSession,
	type HunkBinary,
	type HunkExec,
	type HunkSession,
} from "../hunk-cli.ts";

const WORKTREE = "/worktrees/org/repo/wt/main";
const BINARY: HunkBinary = { executable: "/usr/local/bin/hunk", version: "0.21.1" };

function session(sessionId: string, pid = 1000): HunkSession {
	return { sessionId, pid, repoRoot: WORKTREE, launchedAt: "2026-09-16T00:00:00.000Z" };
}

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

/** Serves each `session list` call the next scripted payload. */
function mockPi(script: ExecResult[]): { pi: HunkExec; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi: HunkExec = {
		exec: (command: string, args: string[], options?: ExecOptions) => {
			calls.push({ command, args, options });
			const next = script.length > 1 ? script.shift() : script[0];
			if (!next) return Promise.reject(new Error("unexpected exec"));
			return Promise.resolve(next);
		},
	};
	return { pi, calls };
}

function list(...sessions: HunkSession[]): ExecResult {
	return { code: 0, stdout: JSON.stringify({ sessions }), stderr: "", killed: false };
}

function daemonDown(): ExecResult {
	return { code: 1, stdout: "", stderr: "daemon starting", killed: false };
}

const NO_SLEEP = (_ms: number) => Promise.resolve();
const POLL = { attempts: 3, intervalMs: 1 };

describe("discoverNewSession", () => {
	test("returns null when nothing new registered", () => {
		const known = session("known");
		expect(discoverNewSession([known], new Set(["known"]))).toEqual({ ok: true, session: null });
	});

	test("returns the one session that registered after the baseline", () => {
		const fresh = session("fresh");
		expect(discoverNewSession([session("known"), fresh], new Set(["known"]))).toEqual({ ok: true, session: fresh });
	});

	test("fails closed when more than one new session appears", () => {
		const discovery = discoverNewSession([session("first"), session("second")], new Set());
		expect(discovery.ok).toBe(false);
		if (!discovery.ok) expect(discovery.reason).toContain("multiple new hunk sessions");
	});

	test("selects only a fresh session owned by the launched pane process", () => {
		const unrelated = session("unrelated", 2000);
		const launched = session("launched", 3000);
		expect(discoverNewSession([unrelated, launched], new Set(), new Set([3000]))).toEqual({
			ok: true,
			session: launched,
		});
	});

	test("returns null when fresh sessions belong to other processes", () => {
		expect(discoverNewSession([session("unrelated", 2000)], new Set(), new Set([3000]))).toEqual({
			ok: true,
			session: null,
		});
	});
});

describe("awaitLaunchedSession", () => {
	test("tolerates a transient daemon failure within the poll window", async () => {
		const fresh = session("fresh");
		const { pi } = mockPi([daemonDown(), list(fresh)]);
		expect(await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP)).toEqual({
			ok: true,
			session: fresh,
		});
	});
	test("refreshes pane PIDs until a launcher child registers", async () => {
		const launched = session("launched", 3000);
		const { pi, calls } = mockPi([list(launched), list(launched)]);
		let processReads = 0;
		const pids = async () => new Set([processReads++ === 0 ? 2000 : 3000]);

		expect(await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP, pids)).toEqual({
			ok: true,
			session: launched,
		});
		expect(processReads).toBe(2);
		expect(calls).toHaveLength(2);
	});

	test("reports a launch that never registers as an empty discovery, not an error", async () => {
		const { pi } = mockPi([list()]);
		expect(await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP)).toEqual({
			ok: true,
			session: null,
		});
	});

	test("returns ambiguity immediately without spending the remaining budget", async () => {
		const { pi, calls } = mockPi([list(session("first"), session("second"))]);
		const discovery = await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP);
		expect(discovery.ok).toBe(false);
		expect(calls).toHaveLength(1);
	});

	test("reports the final discovery failure once the poll budget is spent", async () => {
		const { pi, calls } = mockPi([daemonDown()]);
		const discovery = await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP);
		expect(discovery).toEqual({ ok: false, reason: "exited with code 1: daemon starting" });
		expect(calls).toHaveLength(POLL.attempts);
	});

	test("does not report an earlier transient error when the final poll succeeds empty", async () => {
		const { pi } = mockPi([daemonDown(), list()]);
		expect(await awaitLaunchedSession(pi, BINARY, WORKTREE, new Set(), POLL, NO_SLEEP)).toEqual({
			ok: true,
			session: null,
		});
	});
});
