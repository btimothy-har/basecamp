import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { resetSessionRuntime, setSessionState } from "../../platform/session.ts";
import { registerSafeGitTool } from "../src/safe-git-tool.ts";

interface ExecCall {
	command: string;
	args: string[];
}

interface AppendEntry {
	type: string;
	data: unknown;
}

interface SafeGitTestResult {
	isError?: boolean;
	details: { decision: string; message?: string };
	content: { type: string; text: string }[];
}

interface RegisteredTool {
	name: string;
	execute: (
		id: string,
		params: { command: string; reason: string },
		signal: AbortSignal,
		onUpdate: () => void,
		ctx: { hasUI: boolean; ui: MockUI },
	) => Promise<SafeGitTestResult>;
}

interface MockPi {
	registeredTool: RegisteredTool | null;
	execCalls: ExecCall[];
	appendedEntries: AppendEntry[];
	flags: Record<string, boolean>;

	registerTool(tool: RegisteredTool): void;
	exec(command: string, args: string[], options?: { timeout?: number; cwd?: string }): Promise<ExecResult>;
	appendEntry(type: string, data: unknown): void;
	getFlag(name: string): boolean | undefined;
}

interface ExecResult {
	code: number;
	stdout: string;
	stderr: string;
}

interface MockUI {
	confirmResult: boolean;
	inputResult: string | null;
	confirmCalls: { title: string; body: string }[];
	inputCalls: { prompt: string }[];

	confirm(title: string, body: string): Promise<boolean>;
	input(prompt: string): Promise<string | null>;
}

function createMockUI(): MockUI {
	return {
		confirmResult: true,
		inputResult: null,
		confirmCalls: [],
		inputCalls: [],
		async confirm(title: string, body: string) {
			this.confirmCalls.push({ title, body });
			return this.confirmResult;
		},
		async input(prompt: string) {
			this.inputCalls.push({ prompt });
			return this.inputResult;
		},
	};
}

function createMockPi(): MockPi {
	return {
		registeredTool: null,
		execCalls: [],
		appendedEntries: [],
		flags: {},
		registerTool(tool) {
			this.registeredTool = tool;
		},
		async exec(command: string, args: string[]) {
			this.execCalls.push({ command, args });
			if (args[0] === "branch" && args[1] === "--show-current") {
				return { code: 0, stdout: "feature-branch\n", stderr: "" };
			}
			if (args[0] === "symbolic-ref") {
				return { code: 0, stdout: "origin/main\n", stderr: "" };
			}
			if (args[0] === "rev-parse" && args.includes("@{u}")) {
				return { code: 0, stdout: "origin/feature-branch\n", stderr: "" };
			}
			if (args[0] === "rev-list") {
				return { code: 0, stdout: "0\t2\n", stderr: "" };
			}
			if (args[0] === "status") {
				return { code: 0, stdout: "", stderr: "" };
			}
			if (args[0] === "clean") {
				return { code: 0, stdout: "Would remove file.txt\n", stderr: "" };
			}
			return { code: 0, stdout: "OK\n", stderr: "" };
		},
		appendEntry(type: string, data: unknown) {
			this.appendedEntries.push({ type, data });
		},
		getFlag(name: string) {
			return this.flags[name];
		},
	};
}

function baseSessionState() {
	return {
		projectName: "test-project",
		project: null,
		launchCwd: "/tmp/test-worktree",
		repoRoot: "/tmp/test-repo",
		additionalDirs: [],
		repoName: "test-repo",
		isRepo: true,
		remoteUrl: "git@github.com:test/test-repo.git",
		scratchDir: "/tmp/pi/test-repo",
		workingStyle: "engineering",
		worktreeDir: "/tmp/test-worktree",
		worktreeLabel: "feature",
		worktreeBranch: "bh/feature",
		contextContent: null,
		projectWarnings: [],
		unsafeEdit: false,
	};
}

function noWorktreeSessionState() {
	return {
		...baseSessionState(),
		launchCwd: "/tmp/test-repo",
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
	};
}

function unsafeEditSessionState() {
	return {
		...noWorktreeSessionState(),
		unsafeEdit: true,
	};
}

describe("safe_git tool", () => {
	let mockPi: MockPi;
	let mockUI: MockUI;

	beforeEach(() => {
		resetSessionRuntime();
		mockPi = createMockPi();
		mockUI = createMockUI();
		registerSafeGitTool(mockPi as never);
	});

	afterEach(() => {
		resetSessionRuntime();
		delete process.env.BASECAMP_AGENT_DEPTH;
	});

	async function execute(command: string, reason = "test reason for this operation") {
		assert.ok(mockPi.registeredTool, "Tool should be registered");
		return mockPi.registeredTool.execute("test-id", { command, reason }, new AbortController().signal, () => {}, {
			hasUI: true,
			ui: mockUI,
		});
	}

	async function executeNoUI(command: string, reason = "test reason for this operation") {
		assert.ok(mockPi.registeredTool, "Tool should be registered");
		return mockPi.registeredTool.execute("test-id", { command, reason }, new AbortController().signal, () => {}, {
			hasUI: false,
			ui: mockUI,
		});
	}

	function resultText(result: SafeGitTestResult): string {
		return result.content[0]?.text ?? "";
	}

	describe("auto-approved commands", () => {
		it("executes read-only commands without confirm", async () => {
			setSessionState(baseSessionState());
			const result = await execute("git status");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
			assert.equal(mockUI.confirmCalls.length, 0, "Should not call confirm");
			const statusCall = mockPi.execCalls.find((c) => c.args[0] === "status");
			assert.ok(statusCall, "Should have called git status");
		});

		it("executes mutating commands without confirm when worktree active", async () => {
			setSessionState(baseSessionState());
			const result = await execute("git add -A");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
			assert.equal(mockUI.confirmCalls.length, 0, "Should not call confirm");
			const addCall = mockPi.execCalls.find((c) => c.args[0] === "add");
			assert.ok(addCall, "Should have called git add");
		});

		it("rejects mutating commands without worktree", async () => {
			setSessionState(noWorktreeSessionState());
			const result = await execute("git add -A");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /worktree/i);
		});
	});

	describe("approval-required commands", () => {
		it("calls confirm and typed input for force push then executes", async () => {
			setSessionState(baseSessionState());
			mockUI.confirmResult = true;
			mockUI.inputResult = "git push --force origin feature-branch";

			const result = await execute("git push --force origin feature-branch");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
			assert.equal(mockUI.confirmCalls.length, 1, "Should call confirm once");
			assert.equal(mockUI.inputCalls.length, 1, "Should call input for typed confirmation");
			const pushCall = mockPi.execCalls.find((c) => c.args[0] === "push");
			assert.ok(pushCall, "Should have called git push");
		});

		it("returns declined when user declines confirm", async () => {
			setSessionState(baseSessionState());
			mockUI.confirmResult = false;

			const result = await execute("git push --force origin feature-branch");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "declined");
			assert.match(resultText(result), /declined/i);
			const pushCall = mockPi.execCalls.find((c) => c.args[0] === "push");
			assert.ok(!pushCall, "Should NOT have called git push");
		});

		it("returns declined when typed confirmation does not match", async () => {
			setSessionState(baseSessionState());
			mockUI.confirmResult = true;
			mockUI.inputResult = "wrong command";

			const result = await execute("git push --force origin feature-branch");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "declined");
			assert.match(resultText(result), /typed confirmation/i);
		});
	});

	describe("default branch protection", () => {
		it("blocks approval-required high-risk on default branch before confirm", async () => {
			setSessionState(baseSessionState());
			mockPi.exec = async (_cmd, args) => {
				if (args[0] === "branch" && args[1] === "--show-current") {
					return { code: 0, stdout: "main\n", stderr: "" };
				}
				if (args[0] === "symbolic-ref") {
					return { code: 0, stdout: "origin/main\n", stderr: "" };
				}
				if (args[0] === "rev-parse") {
					return { code: 0, stdout: "origin/main\n", stderr: "" };
				}
				if (args[0] === "rev-list") {
					return { code: 0, stdout: "0\t0\n", stderr: "" };
				}
				if (args[0] === "status") {
					return { code: 0, stdout: "", stderr: "" };
				}
				if (args[0] === "clean") {
					return { code: 0, stdout: "Would remove file.txt\n", stderr: "" };
				}
				return { code: 0, stdout: "", stderr: "" };
			};

			const result = await execute("git push --force origin main");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /default branch/i);
			assert.equal(mockUI.confirmCalls.length, 0, "Should NOT call confirm");
		});
	});

	describe("read-only mode", () => {
		it("allows read-only auto-approved commands", async () => {
			setSessionState(baseSessionState());
			mockPi.flags["read-only"] = true;

			const result = await execute("git status");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
		});

		it("rejects mutating commands", async () => {
			setSessionState(baseSessionState());
			mockPi.flags["read-only"] = true;

			const result = await execute("git add -A");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /read-only mode/i);
		});
	});

	describe("no-UI context", () => {
		it("allows read-only auto-approved commands", async () => {
			setSessionState(baseSessionState());

			const result = await executeNoUI("git status");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
		});

		it("rejects approval-required commands", async () => {
			setSessionState(baseSessionState());

			const result = await executeNoUI("git push --force origin feature-branch");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /non-interactive/i);
		});
	});

	describe("subagent environment", () => {
		it("allows read-only auto-approved commands", async () => {
			setSessionState(baseSessionState());
			process.env.BASECAMP_AGENT_DEPTH = "1";

			const result = await execute("git status");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
		});

		it("rejects mutating commands", async () => {
			setSessionState(baseSessionState());
			process.env.BASECAMP_AGENT_DEPTH = "1";

			const result = await execute("git add -A");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /subagent/i);
		});

		it("rejects approval-required commands", async () => {
			setSessionState(baseSessionState());
			process.env.BASECAMP_AGENT_DEPTH = "1";

			const result = await execute("git push --force origin feature-branch");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /subagent/i);
		});
	});

	describe("audit logging", () => {
		it("logs executed commands to appendEntry", async () => {
			setSessionState(baseSessionState());
			await execute("git status");

			const entry = mockPi.appendedEntries.find((e) => e.type === "safe-git");
			assert.ok(entry, "Should append safe-git entry");
			assert.equal((entry.data as { decision: string }).decision, "executed");
		});

		it("logs rejected commands to appendEntry", async () => {
			setSessionState(noWorktreeSessionState());
			await execute("git add -A");

			const entry = mockPi.appendedEntries.find((e) => e.type === "safe-git");
			assert.ok(entry, "Should append safe-git entry");
			assert.equal((entry.data as { decision: string }).decision, "rejected");
		});
	});

	describe("unsafeEdit mode", () => {
		it("still rejects mutating git commands without worktree", async () => {
			setSessionState(unsafeEditSessionState());
			const result = await execute("git add -A");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /worktree/i);
			const addCall = mockPi.execCalls.find((c) => c.args[0] === "add");
			assert.ok(!addCall, "Should NOT have called git add");
		});

		it("still allows read-only commands", async () => {
			setSessionState(unsafeEditSessionState());
			const result = await execute("git status");

			assert.equal(result.isError, false);
			assert.equal(result.details.decision, "executed");
		});

		it("still rejects approval-required commands without worktree", async () => {
			setSessionState(unsafeEditSessionState());
			const result = await execute("git push --force origin feature-branch");

			assert.equal(result.isError, true);
			assert.equal(result.details.decision, "rejected");
			assert.match(resultText(result), /worktree/i);
		});
	});
});
