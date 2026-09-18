import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import type {
	BeforeAgentStartEvent,
	BeforeAgentStartEventResult,
	ExtensionAPI,
	ExtensionContext,
	ExtensionMode,
} from "@oh-my-pi/pi-coding-agent";
import registerWorkspaceGuidance from "../guidance.ts";

const temporaryDirectories: string[] = [];

function temporaryDirectory(): string {
	const directory = mkdtempSync(path.join(tmpdir(), "basecamp-omp-guidance-"));
	temporaryDirectories.push(directory);
	return directory;
}

function git(cwd: string, args: string[]): void {
	execFileSync("git", args, { cwd, stdio: "ignore" });
}

function gitFixture(): string {
	const root = temporaryDirectory();
	git(root, ["init", "-q"]);
	writeFileSync(path.join(root, "tracked.txt"), "initial\n");
	git(root, ["add", "tracked.txt"]);
	git(root, ["-c", "user.email=test@localhost", "-c", "user.name=Test", "commit", "-qm", "initial"]);
	return realpathSync(root);
}

type GuidanceHandler = (event: BeforeAgentStartEvent, ctx: ExtensionContext) => BeforeAgentStartEventResult | undefined;

function createHandler(): GuidanceHandler {
	let handler: GuidanceHandler | undefined;
	const api = {
		on(event: string, registered: unknown): void {
			if (event === "before_agent_start") handler = registered as GuidanceHandler;
		},
	};
	registerWorkspaceGuidance(api as unknown as ExtensionAPI);
	if (!handler) throw new Error("before_agent_start handler not registered");
	return handler;
}

function invoke(
	handler: GuidanceHandler,
	cwd: string,
	mode: ExtensionMode = "tui",
): BeforeAgentStartEventResult | undefined {
	const event = { type: "before_agent_start", prompt: "work", systemPrompt: ["base prompt"] } as BeforeAgentStartEvent;
	return handler(event, { cwd, mode } as unknown as ExtensionContext);
}

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("workspace guidance", () => {
	test("injects one static reminder across canonical, detached, and branch worktrees", () => {
		const root = gitFixture();
		const detached = path.join(temporaryDirectory(), "detached");
		const branch = path.join(temporaryDirectory(), "branch");
		git(root, ["worktree", "add", "--detach", "-q", detached, "HEAD"]);
		git(root, ["worktree", "add", "-b", "durable", "-q", branch, "HEAD"]);
		const handler = createHandler();

		const guidance = [root, realpathSync(detached), realpathSync(branch)].map(
			(cwd) => invoke(handler, cwd)?.systemPrompt?.[1],
		);

		expect(new Set(guidance).size).toBe(1);
		expect(guidance[0]).toContain("canonical checkout is for inspection and planning");
		expect(guidance[0]).toContain("detached worktree is writable but temporary");
		expect(guidance[0]).toContain("ask the user to run `/wt <branch>`");
		expect(guidance[0]).toContain("branch-backed worktree is durable");
		expect(guidance[0]).not.toContain("Basecamp");
	});

	test("repeats the policy each turn and preserves the incoming system prompt", () => {
		const root = gitFixture();
		const handler = createHandler();

		for (const mode of ["tui", "print"] as const) {
			const result = invoke(handler, root, mode);
			expect(result?.systemPrompt?.[0]).toBe("base prompt");
			expect(result?.systemPrompt?.[1]).toContain("report the required handoff to the primary session");
		}
	});

	test("adds nothing outside Git", () => {
		expect(invoke(createHandler(), temporaryDirectory())).toBeUndefined();
	});
});
