import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDiffCommand } from "#diff/command.ts";
import { sidecarPath } from "#diff/sidecar.ts";

type ExecResult = { code: number; stdout: string; stderr: string; killed: boolean };
type CommandHandler = (args: string[], ctx: unknown) => Promise<void>;

const WORKTREE = "/repo/wt/feature";
const BASE = "43e3afd68b290430804ef6d7cc0fba60336dcd98";

const TAB_CREATED = JSON.stringify({
	result: { root_pane: { pane_id: "w9:p2" }, tab: { tab_id: "w9:t2" } },
});

function ok(stdout = ""): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

interface Harness {
	pi: ExtensionAPI;
	calls: { command: string; args: string[] }[];
	notices: { message: string; type?: string }[];
	sent: { content: string }[];
	run(): Promise<void>;
}

interface HarnessOptions {
	hunkAvailable?: boolean;
	existingSession?: boolean;
	notes?: { filePath: string; newRange?: [number, number]; body: string; source?: string }[];
	confirm?: boolean;
	hasUI?: boolean;
	tabCreateCode?: number;
}

function harness(options: HarnessOptions = {}): Harness {
	const calls: { command: string; args: string[] }[] = [];
	const notices: { message: string; type?: string }[] = [];
	const sent: { content: string }[] = [];
	let handler: CommandHandler | undefined;

	const notes = options.notes ?? [];
	const exec = async (command: string, args: string[]): Promise<ExecResult> => {
		calls.push({ command, args });
		const joined = args.join(" ");
		if (command === "git" && joined.includes("symbolic-ref")) return ok("origin/main");
		if (command === "git" && joined.includes("merge-base")) return ok(BASE);
		if (command === "hunk" && joined === "--version") {
			return options.hunkAvailable === false ? { ...ok(), code: 127 } : ok("0.17.6");
		}
		if (command === "hunk" && joined.startsWith("session get")) {
			return options.existingSession
				? ok(JSON.stringify({ session: { sessionId: "s1", repoRoot: WORKTREE } }))
				: { ...ok(), code: 1 };
		}
		if (command === "hunk" && joined.startsWith("session comment list")) {
			return ok(JSON.stringify({ comments: notes.map((n) => ({ source: "user", ...n })) }));
		}
		if (command === "herdr" && joined.startsWith("tab create")) {
			const code = options.tabCreateCode ?? 0;
			return code === 0 ? ok(TAB_CREATED) : { ...ok(), code };
		}
		if (command === "herdr") return ok('{"result":{"type":"ok"}}');
		throw new Error(`unexpected exec: ${command} ${joined}`);
	};

	const pi = {
		exec,
		events: { emit: () => {} },
		sendMessage: (message: { content: string }) => sent.push(message),
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

	registerDiffCommand(pi);
	return {
		pi,
		calls,
		notices,
		sent,
		run: async () => {
			assert.ok(handler, "/diff was not registered");
			await handler([], ctx);
		},
	};
}

function herdrEnv(t: TestContext, overrides: Record<string, string | undefined> = {}): string {
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
	t.after(() => {
		fs.rmSync(scratch, { recursive: true, force: true });
		for (const [key, value] of originals) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	});
	return scratch;
}

function argsFor(calls: { command: string; args: string[] }[], command: string, prefix: string): string[] | undefined {
	return calls.find((c) => c.command === command && c.args.join(" ").startsWith(prefix))?.args;
}

describe("/diff", () => {
	it("refuses outside Herdr without touching the shell", async (t) => {
		herdrEnv(t, { HERDR_ENV: undefined });
		const h = harness();

		await h.run();

		assert.equal(h.calls.length, 0);
		assert.equal(h.notices[0]?.type, "error");
		assert.match(h.notices[0]?.message ?? "", /not running in Herdr/);
	});

	it("refuses when hunk is missing, before opening a tab", async (t) => {
		herdrEnv(t);
		const h = harness({ hunkAvailable: false });

		await h.run();

		assert.equal(h.notices[0]?.type, "error");
		assert.match(h.notices[0]?.message ?? "", /hunk/);
		assert.equal(argsFor(h.calls, "herdr", "tab create"), undefined);
	});

	it("opens a labelled tab in this workspace and launches hunk on the merge-base", async (t) => {
		herdrEnv(t);
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "tab create"), [
			"tab",
			"create",
			"--workspace",
			"w9",
			"--cwd",
			WORKTREE,
			"--label",
			"diff: feature",
			"--no-focus",
			"--env",
			"HUNK_DISABLE_UPDATE_NOTICE=1",
		]);
		assert.deepEqual(argsFor(h.calls, "herdr", "pane run"), ["pane", "run", "w9:p2", "'hunk'", "'diff'", `'${BASE}'`]);
		assert.deepEqual(argsFor(h.calls, "herdr", "tab close"), ["tab", "close", "w9:t2"]);
		assert.equal(h.sent.length, 0);
		assert.equal(h.notices[0]?.type, "info");
	});

	it("passes the sidecar when one exists for this worktree", async (t) => {
		herdrEnv(t);
		const target = sidecarPath(WORKTREE);
		fs.mkdirSync(path.dirname(target), { recursive: true });
		fs.writeFileSync(target, "{}");
		const h = harness();

		await h.run();

		assert.deepEqual(argsFor(h.calls, "herdr", "pane run")?.slice(4), [
			"'diff'",
			`'${BASE}'`,
			"'--agent-context'",
			`'${target}'`,
		]);
	});

	it("sends line-anchored annotations back into the session", async (t) => {
		herdrEnv(t);
		const h = harness({
			notes: [
				{ filePath: "pi/diff/hunk.ts", newRange: [12, 20], body: "narrow this type" },
				{ filePath: "README.md", newRange: [3, 3], body: "typo" },
			],
		});

		await h.run();

		assert.equal(h.sent.length, 1);
		assert.match(h.sent[0]?.content ?? "", /pi\/diff\/hunk\.ts:12-20/);
		assert.match(h.sent[0]?.content ?? "", /README\.md:3\n/);
		assert.match(h.sent[0]?.content ?? "", /2 annotations/);
	});

	it("still reads annotations when the confirm is cancelled", async (t) => {
		herdrEnv(t);
		const h = harness({ confirm: false, notes: [{ filePath: "a.ts", newRange: [1, 1], body: "keep me" }] });

		await h.run();

		assert.equal(h.sent.length, 1);
		assert.match(h.sent[0]?.content ?? "", /keep me/);
	});

	it("drains a leftover session's notes before closing its tab", async (t) => {
		herdrEnv(t);
		const first = harness({ notes: [{ filePath: "a.ts", newRange: [1, 1], body: "from the first run" }] });
		await first.run();

		// The first run closed its own tab; simulate one that outlived its session.
		const second = harness({ existingSession: true, notes: [{ filePath: "b.ts", newRange: [2, 2], body: "later" }] });
		await second.run();

		const order = second.calls.map((c) => `${c.command} ${c.args.join(" ")}`);
		const readAt = order.findIndex((c) => c.startsWith("hunk session comment list"));
		const tabAt = order.findIndex((c) => c.startsWith("herdr tab create"));
		assert.ok(readAt >= 0 && tabAt >= 0, "expected both a note read and a tab create");
		assert.ok(readAt < tabAt, "leftover notes must be read before a new tab replaces the session");
	});

	it("closes the tab and reports when hunk fails to launch", async (t) => {
		herdrEnv(t);
		const h = harness({ tabCreateCode: 3 });

		await h.run();

		assert.equal(h.notices[0]?.type, "error");
		assert.match(h.notices[0]?.message ?? "", /Herdr tab/);
	});
});
