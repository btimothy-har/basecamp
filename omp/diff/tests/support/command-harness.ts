import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
	ExecOptions,
	ExecResult,
	ExtensionAPI,
	ExtensionCommandContext,
	SessionEntry,
} from "@oh-my-pi/pi-coding-agent";
import { anchorHash, type DiffAnnotation } from "../../annotations.ts";
import type { DiffReviewArtifactV1 } from "../../artifact.ts";
import registerDiffCommand from "../../command.ts";
import { DIFF_ANNOTATION_CUSTOM_TYPE } from "../../journal.ts";
import type { DiffSnapshot } from "../../loader.ts";

const SOURCE = "one\ntwo\nthree\n";
const originalEnv = {
	PATH: process.env.PATH,
	HERDR_ENV: process.env.HERDR_ENV,
	HERDR_SOCKET_PATH: process.env.HERDR_SOCKET_PATH,
	HERDR_PANE_ID: process.env.HERDR_PANE_ID,
	HERDR_WORKSPACE_ID: process.env.HERDR_WORKSPACE_ID,
	BASECAMP_AGENT_DEPTH: process.env.BASECAMP_AGENT_DEPTH,
};
const tempRoots: string[] = [];

export function cleanupCommandHarnesses(): void {
	for (const root of tempRoots.splice(0)) rmSync(root, { recursive: true, force: true });
	for (const [key, value] of Object.entries(originalEnv)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
}

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

interface HarnessOptions {
	confirmed?: boolean;
	comments?: string;
	artifactPath?: string | null;
	contextError?: string;
	paneRunFails?: boolean;
	withAnnotations?: boolean;
	sessionPid?: number;
	sessionChangesAfterSave?: boolean;
	wrappedProcess?: boolean;
	warnings?: string[];
}

function ok(stdout = ""): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

function journalEntry(annotations: DiffAnnotation[]): SessionEntry {
	return {
		id: "journal-1",
		parentId: null,
		timestamp: "2026-09-16T00:00:00.000Z",
		type: "custom",
		customType: DIFF_ANNOTATION_CUSTOM_TYPE,
		data: { v: 1, kind: "recorded", annotations },
	} as SessionEntry;
}

export function createCommandHarness(options: HarnessOptions = {}) {
	const root = mkdtempSync(join(tmpdir(), "omp-diff-command-"));
	tempRoots.push(root);
	mkdirSync(join(root, "src"), { recursive: true });
	writeFileSync(join(root, "src/a.ts"), SOURCE);
	const bin = join(root, "bin");
	mkdirSync(bin);
	const hunk = join(bin, "hunk");
	writeFileSync(hunk, "", { mode: 0o755 });
	process.env.PATH = bin;
	process.env.HERDR_ENV = "1";
	process.env.HERDR_SOCKET_PATH = join(root, "herdr.sock");
	process.env.HERDR_PANE_ID = "w1:p1";
	process.env.HERDR_WORKSPACE_ID = "w1";
	delete process.env.BASECAMP_AGENT_DEPTH;

	const hash = anchorHash("src/a.ts", { start: 2, end: 2 }, SOURCE);
	if (hash === null) throw new Error("expected a valid fixture hash");
	const current: DiffAnnotation = {
		id: "current-id",
		repository: "playground/basecamp",
		path: "src/a.ts",
		newRange: { start: 2, end: 2 },
		anchorHash: hash,
		summary: "Preserve this invariant",
	};
	const stale: DiffAnnotation = { ...current, id: "stale-id", anchorHash: "changed" };
	const snapshot: DiffSnapshot = {
		repositoryRoot: root,
		repository: "playground/basecamp",
		defaultBranch: "main",
		baseRevision: "base;literal",
		headRevision: "head-sha",
		patch: "diff --git a/src/a.ts b/src/a.ts\n@@ -2 +2 @@\n-old\n+two\n",
		files: [{ path: "src/a.ts", newRanges: [{ start: 2, end: 2 }], newLines: new Map([[2, "two"]]) }],
		warnings: options.warnings,
	};
	const calls: ExecCall[] = [];
	let sessionListCalls = 0;
	const comments =
		options.comments ??
		JSON.stringify({
			comments: [
				{ source: "user", filePath: "src/a.ts", newRange: [2, 2], body: "new-side note" },
				{ source: "user", filePath: "src/old.ts", oldRange: [7, 8], body: "removed note" },
			],
		});
	const exec = async (command: string, args: string[], execOptions?: ExecOptions): Promise<ExecResult> => {
		calls.push({ command, args, options: execOptions });
		if (command === hunk && args[0] === "--version") return ok("0.21.1\n");
		if (command === hunk && args.join(" ") === "patch --help") {
			return ok("--agent-context <path>\n--agent-notes\n");
		}
		if (command === hunk && args.join(" ") === "session list --json") {
			sessionListCalls += 1;
			return ok(
				JSON.stringify({
					sessions:
						sessionListCalls === 1
							? []
							: [
									{
										sessionId: "review-session",
										pid: options.sessionPid ?? 4242,
										launchedAt: "2026-09-16T00:00:00Z",
									},
								],
				}),
			);
		}
		if (command === hunk && args[0] === "session" && args[1] === "comment") return ok(comments);
		if (command === "herdr" && args[1] === "split") {
			return ok(JSON.stringify({ result: { pane: { pane_id: "w1:p2", tab_id: "w1:t1" } } }));
		}
		if (command === "herdr" && args[1] === "process-info") {
			const foreground_processes = options.wrappedProcess
				? [
						{ pid: 4100, argv: ["node", hunk, "patch", "/tmp/review.patch"] },
						{ pid: 4242, argv: ["/cache/hunk-native", "patch", "/tmp/review.patch"] },
					]
				: [{ pid: 4242, argv: [hunk, "patch", "/tmp/review.patch"] }];
			return ok(JSON.stringify({ result: { process_info: { foreground_processes } } }));
		}
		if (command === "herdr" && args[1] === "run" && options.paneRunFails) {
			return { ...ok(), killed: true, stderr: "request timed out" };
		}
		if (command === "herdr" && (args[1] === "run" || args[1] === "close")) return ok();
		throw new Error(`unexpected exec: ${command} ${args.join(" ")}`);
	};

	let commandHandler: ((args: string, ctx: ExtensionCommandContext) => Promise<void>) | undefined;
	const appended: { customType: string; data: unknown }[] = [];
	const sent: { content: string; options: unknown }[] = [];
	const notifications: { message: string; level: string }[] = [];
	const events: { channel: string; data: unknown }[] = [];
	const saved: { content: string; toolType: string }[] = [];
	const projected: DiffAnnotation[][] = [];
	const writtenPatches: string[] = [];
	let cleanupCount = 0;
	let loadCount = 0;
	let idleCount = 0;
	let sessionId = "session-1";
	const api = {
		registerCommand(_name: string, definition: { handler: typeof commandHandler }): void {
			commandHandler = definition.handler;
		},
		exec,
		appendEntry(customType: string, data?: unknown): void {
			appended.push({ customType, data });
		},
		sendUserMessage(content: string, sendOptions?: unknown): void {
			sent.push({ content, options: sendOptions });
		},
		events: { emit: (channel: string, data: unknown) => void events.push({ channel, data }) },
	} as unknown as ExtensionAPI;
	registerDiffCommand(api, {
		loadDiff: async () => {
			loadCount += 1;
			return snapshot;
		},
		poll: { attempts: 1, intervalMs: 0 },
		writeAgentContext: (annotations) => {
			if (options.contextError) throw new Error(options.contextError);
			projected.push([...annotations]);
			return {
				path: "/tmp/agent context.json",
				annotations: annotations.length,
				cleanup: () => {
					cleanupCount += 1;
				},
			};
		},
		writeReviewPatch: (patch) => {
			writtenPatches.push(patch);
			return {
				path: "/tmp/review.patch",
				cleanup: () => {
					cleanupCount += 1;
				},
			};
		},
	});
	if (!commandHandler) throw new Error("/diff was not registered");
	const registeredCommand = commandHandler;

	const branch = options.withAnnotations === false ? [] : [journalEntry([current, stale])];
	const artifactPath = options.artifactPath === undefined ? "/artifacts/review.json" : options.artifactPath;
	const ctx = {
		cwd: root,
		mode: "tui",
		hasUI: true,
		waitForIdle: async () => {
			idleCount += 1;
		},
		ui: {
			notify: (message: string, level: string) => void notifications.push({ message, level }),
			confirm: async () => options.confirmed ?? true,
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getBranch: () => branch,
			getArtifactsDir: () => "/artifacts",
			saveArtifact: async (content: string, toolType: string) => {
				saved.push({ content, toolType });
				if (options.sessionChangesAfterSave) sessionId = "session-2";
				return "review-42";
			},
			getArtifactPath: async () => artifactPath,
			putBlob: async () => ({ displayPath: "/blobs/review.json" }),
		},
	} as unknown as ExtensionCommandContext;

	return {
		appended,
		calls,
		events,
		invoke: (args = "") => registeredCommand(args, ctx),
		loadCount: () => loadCount,
		idleCount: () => idleCount,
		notifications,
		projected,
		cleanupCount: () => cleanupCount,
		saved,
		sent,
		writtenPatches,
	};
}

export function savedReview(saved: { content: string }[]): DiffReviewArtifactV1 {
	const entry = saved[0];
	if (!entry) throw new Error("expected a saved review");
	return JSON.parse(entry.content) as DiffReviewArtifactV1;
}
