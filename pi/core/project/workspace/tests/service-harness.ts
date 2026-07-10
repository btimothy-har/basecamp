import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "../../../git/constants.ts";
import { SCRATCH_ROOT } from "../constants.ts";
import { WorkspaceRuntimeService } from "../runtime.ts";

export const REPO_ROOT = "/repo";
// Unique per test-file process. Each *.test.ts runs in its own child process, and
// files sharing this harness would otherwise collide on the fixed /tmp/pi scratch
// base — one process's cleanup rm racing another's recursive mkdir on the same
// path surfaces as an intermittent ENOENT.
const REPO_NAME = `repo-${process.pid}`;
// Derived from REMOTE_URL by resolveGitInfo: <org>/<name>, not the toplevel basename.
export const REPO_IDENTITY = `test/${REPO_NAME}`;
export const LABEL = "feature";
export const BRANCH = "wt/feature";
export const REMOTE_URL = `git@github.com:test/${REPO_NAME}.git`;
export const WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_IDENTITY, LABEL);
export const SCRATCH_DIR = path.join(SCRATCH_ROOT, REPO_IDENTITY);

export interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

type ExecResult = { code: number; stdout: string; stderr: string };

function isWorkspaceEnvKey(key: string): boolean {
	return key.startsWith("BASECAMP_");
}

export function restoreWorkspaceEnv(snapshot: Record<string, string | undefined>): void {
	for (const key of Object.keys(process.env)) {
		if (isWorkspaceEnvKey(key) && !(key in snapshot)) delete process.env[key];
	}
	for (const [key, value] of Object.entries(snapshot)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
}

export function snapshotWorkspaceEnv(): Record<string, string | undefined> {
	return Object.fromEntries(
		Object.entries(process.env)
			.filter(([key]) => isWorkspaceEnvKey(key))
			.map(([key, value]) => [key, value]),
	);
}

export function clearAgentDepthEnv(): void {
	delete process.env.BASECAMP_AGENT_DEPTH;
}

function gitWorktreeListOutput(worktreeDir = WORKTREE_DIR, branch = BRANCH): string {
	return [
		`worktree ${REPO_ROOT}`,
		"branch refs/heads/main",
		"",
		`worktree ${worktreeDir}`,
		`branch refs/heads/${branch}`,
		"",
	].join("\n");
}

export function argsEqual(actual: string[], expected: string[]): boolean {
	return actual.length === expected.length && actual.every((arg, index) => arg === expected[index]);
}

function unexpectedExecCall(call: ExecCall): Error {
	return new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
}

export function createContext(sessionId: string): ExtensionContext {
	return {
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
		},
	} as unknown as ExtensionContext;
}

export function createWorkspaceSessionContext(
	sessionId: string,
	notifications: string[],
	cwd = REPO_ROOT,
): ExtensionContext {
	return {
		cwd,
		hasUI: true,
		ui: {
			notify(message: string) {
				notifications.push(message);
			},
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
		},
	} as unknown as ExtensionContext;
}

export function createPi(piOptions: { worktreeDir?: string; branch?: string; linkedWorktree?: boolean } = {}): {
	pi: ExtensionAPI;
	calls: ExecCall[];
} {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			const call = { command, args, options };
			calls.push(call);

			if (command !== "git") throw unexpectedExecCall(call);
			if (argsEqual(args, ["rev-parse", "--show-toplevel"])) {
				return { code: 0, stdout: `${piOptions.linkedWorktree ? WORKTREE_DIR : REPO_ROOT}\n`, stderr: "" };
			}
			if (argsEqual(args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				return piOptions.linkedWorktree
					? {
							code: 0,
							stdout: `${path.join(REPO_ROOT, ".git", "worktrees", LABEL)}\n${path.join(REPO_ROOT, ".git")}\n`,
							stderr: "",
						}
					: { code: 0, stdout: `${path.join(REPO_ROOT, ".git")}\n${path.join(REPO_ROOT, ".git")}\n`, stderr: "" };
			}
			if (argsEqual(args, ["-C", piOptions.linkedWorktree ? WORKTREE_DIR : REPO_ROOT, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${REMOTE_URL}\n`, stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
				return { code: 0, stdout: "origin/main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "branch", "--show-current"])) {
				return { code: 0, stdout: "main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "status", "--porcelain"])) {
				return { code: 0, stdout: "", stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: gitWorktreeListOutput(piOptions.worktreeDir, piOptions.branch), stderr: "" };
			}

			throw unexpectedExecCall(call);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

export function createLinkedWorktreePi(options: { toplevel: string; branch: string | null }): {
	pi: ExtensionAPI;
	calls: ExecCall[];
} {
	const { toplevel, branch } = options;
	const calls: ExecCall[] = [];
	const worktreeBranchLine = branch === null ? "detached" : `branch refs/heads/${branch}`;
	const listOutput = [
		`worktree ${REPO_ROOT}`,
		"branch refs/heads/main",
		"",
		`worktree ${toplevel}`,
		worktreeBranchLine,
		"",
	].join("\n");
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			const call = { command, args, options };
			calls.push(call);
			if (command !== "git") throw unexpectedExecCall(call);
			if (argsEqual(args, ["rev-parse", "--show-toplevel"])) return { code: 0, stdout: `${toplevel}\n`, stderr: "" };
			if (argsEqual(args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				return {
					code: 0,
					stdout: `${path.join(REPO_ROOT, ".git", "worktrees", "wt")}\n${path.join(REPO_ROOT, ".git")}\n`,
					stderr: "",
				};
			}
			if (argsEqual(args, ["-C", toplevel, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${REMOTE_URL}\n`, stderr: "" };
			}
			if (argsEqual(args, ["-C", REPO_ROOT, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: listOutput, stderr: "" };
			}
			throw unexpectedExecCall(call);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

export function createSessionPi(options: { worktreeDir: string; branch: string; linkedWorktree?: boolean }): {
	pi: ExtensionAPI;
	calls: ExecCall[];
	sessionStart: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>;
} {
	const { pi, calls } = createPi(options);
	let sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;
	const sessionPi = {
		...pi,
		registerFlag() {},
		getFlag() {
			return undefined;
		},
		on(event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) {
			if (event === "session_start") sessionStart = handler;
		},
	} as unknown as ExtensionAPI;
	return {
		pi: sessionPi,
		calls,
		sessionStart(event, ctx) {
			if (!sessionStart) throw new Error("session_start handler was not registered");
			return sessionStart(event, ctx);
		},
	};
}

export async function initializeAndActivate(
	launchCwd: string,
): Promise<{ service: WorkspaceRuntimeService; calls: ExecCall[] }> {
	const { pi, calls } = createPi();
	const service = new WorkspaceRuntimeService(pi);
	await service.initialize({
		launchCwd,
		unsafeEditFlag: false,
		unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
	});
	await service.activateWorktree(LABEL);
	return { service, calls };
}
