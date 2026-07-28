/** Shared fake exec layer and environment scaffolding for the /diff command tests. */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { forgetCheckpoint, recordCheckpoint } from "#diff/checkpoints.ts";
import { registerDiffCommand } from "#diff/command.ts";
import { forgetTab } from "#diff/session-state.ts";

type ExecResult = { code: number; stdout: string; stderr: string; killed: boolean };
type CommandHandler = (args: string, ctx: unknown) => Promise<void>;
export type Note = { filePath: string; newRange?: [number, number]; body: string };

export const WORKTREE = "/repo/wt/feature";
export const BASE = "43e3afd68b290430804ef6d7cc0fba60336dcd98";
export const HEAD_SHA = "55aa55aa55aa55aa55aa55aa55aa55aa55aa55aa";
export const PREV_SHA = "99bb99bb99bb99bb99bb99bb99bb99bb99bb99bb";
export const NEW_SESSION = "11111111-1111-1111-1111-111111111111";
export const STALE_SESSION = "22222222-2222-2222-2222-222222222222";

const TAB_CREATED = JSON.stringify({ result: { root_pane: { pane_id: "w9:p2" }, tab: { tab_id: "w9:t2" } } });

function ok(stdout = ""): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

function sessionList(ids: string[]): ExecResult {
	return ok(JSON.stringify({ sessions: ids.map((id) => ({ sessionId: id, repoRoot: WORKTREE, launchedAt: id })) }));
}

export interface Harness {
	calls: { command: string; args: string[] }[];
	notices: { message: string; type?: string }[];
	sent: { content: string }[];
	run(): Promise<void>;
}

export interface HarnessOptions {
	hunkAvailable?: boolean;
	/** Sessions already live before /diff runs. */
	preexisting?: string[];
	/** hunk never registers, simulating a launch that died. */
	neverRegisters?: boolean;
	/** Consumed one per `comment list`, so carried and fresh notes differ. */
	noteReads?: (Note[] | { fail: string })[];
	confirm?: boolean;
	hasUI?: boolean;
	tabCreateCode?: number;
	paneRunCode?: number;
	tabCloseCode?: number;
	/** Arguments the run is invoked with, e.g. "last". */
	args?: string;
	/** Checkpoint recorded before the run, as if an earlier /diff completed. */
	checkpoint?: { base: string; last: string };
	/** False when the recorded checkpoint is not an ancestor of HEAD (rebase, sibling branch). */
	checkpointIsAncestor?: boolean;
}

export function harness(options: HarnessOptions = {}): Harness {
	const calls: { command: string; args: string[] }[] = [];
	const notices: { message: string; type?: string }[] = [];
	const sent: { content: string }[] = [];
	let handler: CommandHandler | undefined;

	const reads = [...(options.noteReads ?? [])];
	let launched = false;

	const exec = async (command: string, args: string[]): Promise<ExecResult> => {
		calls.push({ command, args });
		const joined = args.join(" ");
		if (command === "git" && joined.includes("symbolic-ref")) return ok("origin/main");
		if (command === "git" && joined.includes("merge-base --is-ancestor")) {
			return options.checkpointIsAncestor === false ? { ...ok(), code: 1 } : ok();
		}
		if (command === "git" && joined.includes("merge-base")) return ok(BASE);
		if (command === "git" && joined.includes("rev-parse") && joined.includes("HEAD")) return ok(HEAD_SHA);
		if (command === "hunk" && joined === "--version") {
			return options.hunkAvailable === false ? { ...ok(), code: 127 } : ok("0.17.6");
		}
		if (command === "hunk" && joined.startsWith("session list")) {
			const live = [...(options.preexisting ?? [])];
			if (launched && !options.neverRegisters) live.push(NEW_SESSION);
			return sessionList(live);
		}
		if (command === "hunk" && joined.startsWith("session comment list")) {
			const next = reads.shift() ?? [];
			if (!Array.isArray(next)) return { code: 1, stdout: "", stderr: next.fail, killed: false };
			return ok(JSON.stringify({ comments: next.map((n) => ({ source: "user", ...n })) }));
		}
		if (command === "herdr" && joined.startsWith("tab create")) {
			const code = options.tabCreateCode ?? 0;
			return code === 0 ? ok(TAB_CREATED) : { ...ok(), code };
		}
		if (command === "herdr" && joined.startsWith("pane run")) {
			const code = options.paneRunCode ?? 0;
			if (code === 0) launched = true;
			return code === 0 ? ok() : { ...ok(), code };
		}
		if (command === "herdr" && joined.startsWith("tab close")) {
			const code = options.tabCloseCode ?? 0;
			return code === 0 ? ok('{"result":{"type":"ok"}}') : { ...ok(), code };
		}
		throw new Error(`unexpected exec: ${command} ${joined}`);
	};

	const pi = {
		exec,
		events: { emit: () => {} },
		// Returns void, like the real ExtensionAPI surface: the session reports its
		// own delivery failures, so extension code is handed no result to await.
		sendUserMessage: (content: string) => {
			sent.push({ content });
		},
		registerCommand: (_name: string, spec: { handler: CommandHandler }) => {
			handler = spec.handler;
		},
	} as unknown as ExtensionAPI;

	const ctx = {
		hasUI: options.hasUI ?? true,
		cwd: WORKTREE,
		ui: {
			notify: (message: string, type?: string) => notices.push({ message, type }),
			confirm: async () => options.confirm ?? true,
		},
	};

	if (options.checkpoint) recordCheckpoint(WORKTREE, options.checkpoint);

	registerDiffCommand(pi, { attempts: 3, intervalMs: 1 });
	return {
		calls,
		notices,
		sent,
		run: async () => {
			assert.ok(handler, "/diff was not registered");
			await handler(options.args ?? "", ctx);
		},
	};
}

export function herdrEnv(t: TestContext, overrides: Record<string, string | undefined> = {}): string {
	const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "diff-cmd-"));
	const vars: Record<string, string | undefined> = {
		HERDR_ENV: "1",
		HERDR_SOCKET_PATH: "/tmp/herdr.sock",
		HERDR_PANE_ID: "w9:p1",
		HERDR_WORKSPACE_ID: "w9",
		BASECAMP_AGENT_DEPTH: undefined,
		BASECAMP_WORKTREE_DIR: WORKTREE,
		BASECAMP_WORKTREE_LABEL: "feature",
		BASECAMP_SCRATCH_DIR: scratch,
		...overrides,
	};
	const originals = new Map<string, string | undefined>();
	for (const [key, value] of Object.entries(vars)) {
		originals.set(key, process.env[key]);
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
	// Surviving state outlives a single test, so every case starts from empty.
	forgetTab(WORKTREE);
	forgetCheckpoint(WORKTREE);
	t.after(() => {
		forgetTab(WORKTREE);
		forgetCheckpoint(WORKTREE);
		fs.rmSync(scratch, { recursive: true, force: true });
		for (const [key, value] of originals) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	});
	return scratch;
}
