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
} from "@oh-my-pi/pi-coding-agent";
import type { WorkspaceEnvironment } from "../environment.ts";
import registerWorkspaceGuidance from "../guidance.ts";
import { RepositoryCache } from "../repository.ts";

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

function createHandler(env: WorkspaceEnvironment): GuidanceHandler {
	let handler: GuidanceHandler | undefined;
	const api = {
		on(event: string, registered: unknown): void {
			if (event === "before_agent_start") handler = registered as GuidanceHandler;
		},
	};
	registerWorkspaceGuidance(api as unknown as ExtensionAPI, { env, repos: new RepositoryCache() });
	if (!handler) throw new Error("before_agent_start handler not registered");
	return handler;
}

function invoke(handler: GuidanceHandler, cwd: string): BeforeAgentStartEventResult | undefined {
	const event = { type: "before_agent_start", prompt: "work", systemPrompt: ["base prompt"] } as BeforeAgentStartEvent;
	return handler(event, { cwd, mode: "tui" } as unknown as ExtensionContext);
}

const noEnv: WorkspaceEnvironment = { protectedRoot: null, scratchRoot: null, inheritedWip: null };

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true, force: true });
});

describe("workspace guidance", () => {
	test("marks the canonical checkout read-only on every prompt", () => {
		const root = gitFixture();
		const handler = createHandler(noEnv);

		const first = invoke(handler, root);
		const second = invoke(handler, root);

		for (const result of [first, second]) {
			expect(result?.systemPrompt?.[0]).toBe("base prompt");
			expect(result?.systemPrompt?.[1]).toContain("canonical checkout");
			expect(result?.systemPrompt?.[1]).toContain("ask the user to run `/wt <branch>`");
			expect(result?.systemPrompt?.[1]).toContain("Approval does not change workspaces");
		}
	});

	test("identifies an inherited-WIP automatic scratch without persistent state", () => {
		const root = gitFixture();
		const scratch = path.join(temporaryDirectory(), "scratch");
		git(root, ["worktree", "add", "--detach", "-q", scratch, "HEAD"]);
		const realScratch = realpathSync(scratch);
		const handler = createHandler({ protectedRoot: root, scratchRoot: realScratch, inheritedWip: true });

		const result = invoke(handler, realScratch);

		expect(result?.systemPrompt?.[1]).toContain("temporary Basecamp scratch worktree");
		expect(result?.systemPrompt?.[1]).toContain("uncommitted work copied from the canonical checkout");
		expect(result?.systemPrompt?.[1]).toContain("carries the session and changes into a branch-backed worktree");
	});

	test("permits implementation in a branch-backed worktree", () => {
		const root = gitFixture();
		const worktree = path.join(temporaryDirectory(), "durable");
		git(root, ["worktree", "add", "-b", "durable", "-q", worktree, "HEAD"]);

		const result = invoke(createHandler(noEnv), realpathSync(worktree));

		expect(result?.systemPrompt?.[1]).toContain("durable branch worktree");
		expect(result?.systemPrompt?.[1]).toContain("branch durable");
		expect(result?.systemPrompt?.[1]).toContain("implementation may proceed");
	});

	test("recomputes guidance from live cwd after a session switch", () => {
		const root = gitFixture();
		const worktree = path.join(temporaryDirectory(), "durable");
		git(root, ["worktree", "add", "-b", "switched", "-q", worktree, "HEAD"]);
		const handler = createHandler(noEnv);

		expect(invoke(handler, root)?.systemPrompt?.[1]).toContain("canonical checkout");
		expect(invoke(handler, realpathSync(worktree))?.systemPrompt?.[1]).toContain("durable branch worktree");
	});

	test("adds nothing outside Git", () => {
		expect(invoke(createHandler(noEnv), temporaryDirectory())).toBeUndefined();
	});
});
