import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { SessionState } from "../../platform/config.ts";
import { resetSessionRuntime, setSessionState } from "../../platform/session.ts";
import { type GitStatusDetails, registerStatusTool } from "../src/status.ts";

interface RegisteredTool {
	name: string;
	execute: () => Promise<{
		isError?: boolean;
		details: GitStatusDetails | null;
		content: Array<{ type: string; text: string }>;
	}>;
}

interface MockExecResult {
	code: number;
	stdout: string;
	stderr: string;
}

type ExecHandler = (command: string, args: string[]) => MockExecResult;

function createMockPi(execHandler: ExecHandler): {
	pi: Parameters<typeof registerStatusTool>[0];
	getRegisteredTool: () => RegisteredTool | null;
} {
	let registeredTool: RegisteredTool | null = null;

	const pi = {
		registerTool(tool: RegisteredTool) {
			registeredTool = tool;
		},
		exec(command: string, args: string[], _options?: unknown): Promise<MockExecResult> {
			return Promise.resolve(execHandler(command, args));
		},
	} as unknown as Parameters<typeof registerStatusTool>[0];

	return { pi, getRegisteredTool: () => registeredTool };
}

const REPO_ROOT = "/Users/test/src/github.com/user/repo";
const WORKTREE_DIR = "/Users/test/.worktrees/repo/wt-label";
const WORKTREE_LABEL = "wt-label";
const WORKTREE_BRANCH = "wt/feature-branch";

function baseSessionState(overrides: Partial<SessionState> = {}): SessionState {
	return {
		projectName: "test-project",
		project: null,
		launchCwd: REPO_ROOT,
		repoRoot: REPO_ROOT,
		additionalDirs: [],
		repoName: "repo",
		isRepo: true,
		remoteUrl: "git@github.com:user/repo.git",
		scratchDir: "/tmp/pi/repo",
		workingStyle: "engineering",
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent: null,
		projectWarnings: [],
		unsafeEdit: false,
		...overrides,
	};
}

function activeWorktreeState(): SessionState {
	return baseSessionState({
		worktreeDir: WORKTREE_DIR,
		worktreeLabel: WORKTREE_LABEL,
		worktreeBranch: WORKTREE_BRANCH,
	});
}

function createGitExecHandler(effectiveRoot: string, branch = "main"): ExecHandler {
	return (command: string, args: string[]) => {
		if (command !== "git") {
			return { code: 1, stdout: "", stderr: `Unknown command: ${command}` };
		}

		const cmd = args[0];

		if (cmd === "rev-parse" && args.includes("--show-toplevel")) {
			return { code: 0, stdout: effectiveRoot, stderr: "" };
		}

		if (cmd === "branch" && args.includes("--show-current")) {
			return { code: 0, stdout: branch, stderr: "" };
		}

		if (cmd === "symbolic-ref" && args.includes("refs/remotes/origin/HEAD")) {
			return { code: 0, stdout: "origin/main", stderr: "" };
		}

		if (cmd === "rev-parse" && args.includes("@{u}")) {
			return { code: 0, stdout: "origin/main", stderr: "" };
		}

		if (cmd === "rev-list" && args.includes("--left-right")) {
			return { code: 0, stdout: "0\t1", stderr: "" };
		}

		if (cmd === "status" && args.includes("--short")) {
			return { code: 0, stdout: " M file.ts\n?? new.ts", stderr: "" };
		}

		if (cmd === "log" && args.includes("--oneline")) {
			return { code: 0, stdout: "abc123 feat: add feature\ndef456 fix: bug fix", stderr: "" };
		}

		return { code: 0, stdout: "", stderr: "" };
	};
}

afterEach(() => {
	resetSessionRuntime();
});

describe("git_status", () => {
	it("shows repository root in inactive session (no worktree)", async () => {
		setSessionState(baseSessionState());
		const { pi, getRegisteredTool } = createMockPi(createGitExecHandler(REPO_ROOT));

		registerStatusTool(pi);
		const tool = getRegisteredTool();
		assert.ok(tool, "Tool should be registered");
		assert.equal(tool.name, "git_status");

		const result = await tool.execute();

		assert.ok(!result.isError, "Should not be an error");
		assert.ok(result.details, "Should have details");

		const details = result.details;
		assert.equal(details.repoName, "repo");
		assert.equal(details.repoRoot, REPO_ROOT);
		assert.equal(details.effectiveRoot, REPO_ROOT);
		assert.equal(details.worktree, null, "worktree should be null when inactive");

		const text = result.content[0]?.text ?? "";
		assert.ok(text.includes("Repository: repo"), "Should show repository name");
		assert.ok(text.includes(`Repository root: ${REPO_ROOT}`), "Should show repository root");
		assert.ok(!text.includes("Protected checkout"), "Should NOT show protected checkout in inactive session");
		assert.ok(!text.includes("Active worktree"), "Should NOT show active worktree in inactive session");
	});

	it("shows protected checkout and worktree info in active worktree session", async () => {
		setSessionState(activeWorktreeState());
		const { pi, getRegisteredTool } = createMockPi(createGitExecHandler(WORKTREE_DIR, WORKTREE_BRANCH));

		registerStatusTool(pi);
		const tool = getRegisteredTool();
		assert.ok(tool, "Tool should be registered");

		const result = await tool.execute();

		assert.ok(!result.isError, "Should not be an error");
		assert.ok(result.details, "Should have details");

		const details = result.details;
		assert.equal(details.repoName, "repo");
		assert.equal(details.repoRoot, REPO_ROOT, "repoRoot should be protected checkout");
		assert.equal(details.effectiveRoot, WORKTREE_DIR, "effectiveRoot should be worktree dir");

		assert.ok(details.worktree, "worktree should be set when active");
		assert.equal(details.worktree?.label, WORKTREE_LABEL);
		assert.equal(details.worktree?.path, WORKTREE_DIR);
		assert.equal(details.worktree?.branch, WORKTREE_BRANCH);

		const text = result.content[0]?.text ?? "";
		assert.ok(text.includes("Repository: repo"), "Should show repository name");
		assert.ok(text.includes(`Protected checkout: ${REPO_ROOT}`), "Should show protected checkout");
		assert.ok(text.includes(`Active worktree: ${WORKTREE_LABEL}`), "Should show active worktree label");
		assert.ok(text.includes(`Worktree root: ${WORKTREE_DIR}`), "Should show worktree root");
		assert.ok(text.includes("Git status source: active worktree"), "Should clarify git status source");
		assert.ok(!text.includes(`Repository root: ${WORKTREE_DIR}`), "Should NOT show worktree as repository root");
	});

	it("falls back to git root when session state is unavailable", async () => {
		resetSessionRuntime();
		const { pi, getRegisteredTool } = createMockPi(createGitExecHandler(REPO_ROOT));

		registerStatusTool(pi);
		const tool = getRegisteredTool();
		assert.ok(tool, "Tool should be registered");

		const result = await tool.execute();

		assert.ok(!result.isError, "Should not be an error");
		assert.ok(result.details, "Should have details");

		const details = result.details;
		assert.equal(details.repoName, "repo", "Should derive repoName from path");
		assert.equal(details.repoRoot, REPO_ROOT, "Should use effectiveRoot as fallback");
		assert.equal(details.effectiveRoot, REPO_ROOT);
		assert.equal(details.worktree, null);

		const text = result.content[0]?.text ?? "";
		assert.ok(text.includes(`Git root: ${REPO_ROOT}`), "Should show 'Git root' label in fallback mode");
		assert.ok(!text.includes("Repository:"), "Should NOT use 'Repository:' without session state");
	});

	it("returns structured details with branch, status, and commits", async () => {
		setSessionState(baseSessionState());
		const { pi, getRegisteredTool } = createMockPi(createGitExecHandler(REPO_ROOT));

		registerStatusTool(pi);
		const tool = getRegisteredTool();
		assert.ok(tool);

		const result = await tool.execute();
		assert.ok(result.details);

		const details = result.details;
		assert.equal(details.branch, "main");
		assert.equal(details.defaultBranch, "main");
		assert.equal(details.upstream, "origin/main (ahead 1, behind 0)");
		assert.deepEqual(details.workingTreeStatus, [" M file.ts", "?? new.ts"]);
		assert.deepEqual(details.recentCommits, ["abc123 feat: add feature", "def456 fix: bug fix"]);
	});

	it("handles non-git directory gracefully", async () => {
		setSessionState(baseSessionState());
		const { pi, getRegisteredTool } = createMockPi(() => ({
			code: 128,
			stdout: "",
			stderr: "fatal: not a git repository",
		}));

		registerStatusTool(pi);
		const tool = getRegisteredTool();
		assert.ok(tool);

		const result = await tool.execute();

		assert.ok(result.isError, "Should be an error");
		assert.equal(result.details, null, "Error result should have null details");
		assert.ok(result.content[0]?.text.includes("not a git repository"));
	});
});
