import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, ExtensionMode } from "@oh-my-pi/pi-coding-agent";
import { RepositoryCache } from "../repository.ts";
import registerStartupWarning from "../startup.ts";

const temporaryDirectories: string[] = [];

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) {
		rmSync(directory, { recursive: true, force: true });
	}
});

function temporaryDirectory(): string {
	const directory = mkdtempSync(path.join(tmpdir(), "basecamp-omp-startup-"));
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

interface Notice {
	message: string;
	type: string | undefined;
}

interface Harness {
	notices: Notice[];
	start(cwd: string, mode?: ExtensionMode): void;
	switchTo(cwd: string, mode?: ExtensionMode): void;
}

function createHarness(): Harness {
	const notices: Notice[] = [];
	const handlers = new Map<string, (ctx: ExtensionContext) => void>();
	const api = {
		on(event: string, handler: (event: unknown, ctx: ExtensionContext) => void): void {
			handlers.set(event, (ctx: ExtensionContext) => handler(undefined, ctx));
		},
	};
	registerStartupWarning(api as unknown as ExtensionAPI, new RepositoryCache());
	const contextFor = (cwd: string, mode: ExtensionMode): ExtensionContext =>
		({
			cwd,
			mode,
			ui: { notify: (message: string, type?: string) => notices.push({ message, type }) },
		}) as unknown as ExtensionContext;
	return {
		notices,
		start: (cwd, mode = "tui") => handlers.get("session_start")?.(contextFor(cwd, mode)),
		switchTo: (cwd, mode = "tui") => handlers.get("session_switch")?.(contextFor(cwd, mode)),
	};
}

describe("workspace startup warning", () => {
	test("warns once on canonical start, including nested cwd and feature branches", () => {
		const root = gitFixture();
		const harness = createHarness();
		harness.start(path.join(root, "nested", "dir"));
		expect(harness.notices).toHaveLength(1);
		expect(harness.notices[0]?.type).toBe("warning");
		expect(harness.notices[0]?.message).toContain(root);
		harness.start(root); // same canonical entry does not repeat
		expect(harness.notices).toHaveLength(1);

		const branched = gitFixture();
		git(branched, ["checkout", "-qb", "feature"]);
		const branchHarness = createHarness();
		branchHarness.start(branched);
		expect(branchHarness.notices).toHaveLength(1);
	});

	test("does not warn for linked worktrees, non-Git cwd, or non-TUI modes", () => {
		const root = gitFixture();
		const linked = path.join(temporaryDirectory(), "linked");
		git(root, ["worktree", "add", "-q", "-b", "linked-branch", linked]);
		const harness = createHarness();
		harness.start(realpathSync(linked));
		harness.start(temporaryDirectory());
		harness.start(root, "print"); // task/headless host
		harness.start(root, "rpc");
		expect(harness.notices).toHaveLength(0);
	});

	test("warns again when a session switch re-enters canonical", () => {
		const root = gitFixture();
		const linked = path.join(temporaryDirectory(), "linked");
		git(root, ["worktree", "add", "-q", "-b", "linked-branch", linked]);
		const harness = createHarness();
		harness.start(realpathSync(linked));
		harness.switchTo(root); // entering canonical
		expect(harness.notices).toHaveLength(1);
		harness.switchTo(root); // no repeat within the same entry
		expect(harness.notices).toHaveLength(1);
		harness.switchTo(realpathSync(linked));
		harness.switchTo(root); // re-entry warns again
		expect(harness.notices).toHaveLength(2);
	});
});
