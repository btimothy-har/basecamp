import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, ToolCallEvent, ToolCallEventResult } from "@oh-my-pi/pi-coding-agent";
import type { WorkspaceEnvironment } from "../environment.ts";
import registerWorkspaceGuard, { CANONICAL_BLOCK_REASON } from "../guard.ts";
import { RepositoryCache } from "../repository.ts";

const temporaryDirectories: string[] = [];

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) {
		rmSync(directory, { recursive: true, force: true });
	}
});

function temporaryDirectory(): string {
	const directory = mkdtempSync(path.join(tmpdir(), "basecamp-omp-guard-"));
	temporaryDirectories.push(directory);
	return directory;
}

function git(cwd: string, args: string[]): void {
	execFileSync("git", args, { cwd, stdio: "ignore" });
}

/** Real Git checkout with one commit; returns its realpath. */
function gitFixture(): string {
	const root = temporaryDirectory();
	git(root, ["init", "-q"]);
	writeFileSync(path.join(root, "tracked.txt"), "initial\n");
	git(root, ["add", "tracked.txt"]);
	git(root, ["-c", "user.email=test@localhost", "-c", "user.name=Test", "commit", "-qm", "initial"]);
	return realpathSync(root);
}

type GuardHandler = (event: ToolCallEvent, ctx: ExtensionContext) => ToolCallEventResult | undefined;

function createHarness(env: WorkspaceEnvironment, repos = new RepositoryCache()): { handler: GuardHandler } {
	let handler: GuardHandler | undefined;
	const api = {
		on(event: string, registered: unknown): void {
			if (event === "tool_call") handler = registered as GuardHandler;
		},
	};
	registerWorkspaceGuard(api as unknown as ExtensionAPI, { env, repos });
	if (!handler) throw new Error("tool_call handler not registered");
	return { handler };
}

function contextFor(cwd: string, artifactsDir?: string): ExtensionContext {
	return {
		cwd,
		mode: "tui",
		localProtocolOptions: artifactsDir
			? { getArtifactsDir: () => artifactsDir, getSessionId: () => "test" }
			: undefined,
	} as unknown as ExtensionContext;
}

function call(toolName: string, input: Record<string, unknown>): ToolCallEvent {
	return { type: "tool_call", toolCallId: "call-1", toolName, input } as ToolCallEvent;
}

const noEnv: WorkspaceEnvironment = { protectedRoot: null, scratchRoot: null, inheritedWip: null };

describe("workspace guard", () => {
	test("blocks write targets inside the canonical checkout", () => {
		const root = gitFixture();
		const { handler } = createHarness(noEnv);
		const ctx = contextFor(root);
		const blocked = [
			{ path: "notes.md" },
			{ path: path.join(root, "notes.md") },
			{ path: "src/../notes.md" },
			{ path: "[notes.md#ABCD]" },
			{ path: "bundle.zip:inner/file.txt" },
			{ path: "data.sqlite:items:42" },
		];
		for (const input of blocked) {
			const result = handler(call("write", { ...input, content: "x" }), ctx);
			expect(result).toEqual({ block: true, reason: CANONICAL_BLOCK_REASON });
		}
	});

	test("blocks through a symlink nested in a scratch outside canonical", () => {
		const root = gitFixture();
		const scratch = temporaryDirectory();
		symlinkSync(root, path.join(scratch, "link"));
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const result = handler(call("write", { path: "link/pwned.txt", content: "x" }), contextFor(scratch));
		expect(result?.block).toBe(true);
	});

	test("blocks through a dangling symlink whose target is canonical", () => {
		const root = gitFixture();
		const scratch = temporaryDirectory();
		symlinkSync(path.join(root, "missing"), path.join(scratch, "dangling"));
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const result = handler(call("write", { path: "dangling/new.txt", content: "x" }), contextFor(scratch));
		expect(result?.block).toBe(true);
	});

	test("blocks local URL writes backed by the canonical checkout", () => {
		const root = gitFixture();
		const scratch = temporaryDirectory();
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const result = handler(call("write", { path: "local://notes.md", content: "x" }), contextFor(scratch, root));
		expect(result?.block).toBe(true);
	});

	test("permits lookalike prefixes, scratch, tmp, and unknown tools", () => {
		const root = gitFixture();
		const lookalike = `${root}-fork`;
		mkdirSync(lookalike, { recursive: true });
		const { handler } = createHarness(noEnv);
		const ctx = contextFor(root);
		for (const target of [`${lookalike}/notes.md`, path.join(tmpdir(), "scratch-note.md")]) {
			expect(handler(call("write", { path: target, content: "x" }), ctx)).toBeUndefined();
		}
		expect(handler(call("write", { path: "local://plan.md", content: "x" }), ctx)).toBeUndefined();
		expect(handler(call("write", { path: "xd://lsp", content: "{}" }), ctx)).toBeUndefined();
		for (const toolName of ["bash", "eval", "task", "mcp_server_tool", "read"]) {
			expect(handler(call(toolName, { command: `rm -rf ${root}` }), ctx)).toBeUndefined();
		}
	});

	test("blocks edit targets including patch rename and apply_patch move destinations", () => {
		const root = gitFixture();
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const ctx = contextFor(temporaryDirectory());
		const cases: Record<string, unknown>[] = [
			{ path: path.join(root, "a.txt"), old_string: "a", new_string: "b" },
			{ path: "outside.txt", edits: [{ op: "update", rename: path.join(root, "moved.txt"), diff: "@@\n" }] },
			{ path: path.join(root, "a.txt"), edits: [{ op: "delete" }] },
			{ input: `*** Begin Patch\n*** Add File: ${path.join(root, "new.txt")}\n+hi\n*** End Patch\n` },
			{
				input: `*** Begin Patch\n*** Update File: outside.txt\n*** Move to: ${path.join(root, "moved.txt")}\n@@\n*** End Patch\n`,
			},
		];
		for (const input of cases) {
			const result = handler(call("edit", input), ctx);
			expect(result).toEqual({ block: true, reason: CANONICAL_BLOCK_REASON });
		}
		expect(handler(call("edit", { path: "outside.txt", old_string: "a", new_string: "b" }), ctx)).toBeUndefined();
	});

	test("blocks ast_edit scopes within, containing, or delimited with the canonical root", async () => {
		const root = gitFixture();
		const outside = temporaryDirectory();
		const { handler } = createHarness(noEnv);
		const ctx = contextFor(root);
		expect((await handler(call("ast_edit", { ops: [], paths: ["src/**/*.ts"] }), ctx))?.block).toBe(true);
		expect((await handler(call("ast_edit", { ops: [], paths: ["."] }), ctx))?.block).toBe(true);
		expect((await handler(call("ast_edit", { ops: [], paths: [path.dirname(root)] }), ctx))?.block).toBe(true);
		expect(
			await handler(call("ast_edit", { ops: [], paths: [`${outside}/safe.ts;${root}/src`] }), contextFor(outside)),
		).toEqual({ block: true, reason: CANONICAL_BLOCK_REASON });
		expect(
			await handler(call("ast_edit", { ops: [], paths: [path.join(tmpdir(), "elsewhere/**/*.ts")] }), ctx),
		).toBeUndefined();
		expect(await handler(call("ast_edit", { ops: [], paths: ["local://draft.ts"] }), ctx)).toBeUndefined();
	});

	test("blocks applying LSP refactors into canonical but not previews or reads", () => {
		const root = gitFixture();
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const ctx = contextFor(temporaryDirectory());
		const inside = path.join(root, "mod.ts");
		expect(handler(call("lsp", { action: "rename", file: inside, new_name: "renamed" }), ctx)?.block).toBe(true);
		expect(handler(call("lsp", { action: "rename", file: inside, apply: false }), ctx)).toBeUndefined();
		expect(handler(call("lsp", { action: "rename_file", file: "x.ts", new_name: inside }), ctx)?.block).toBe(true);
		expect(handler(call("lsp", { action: "code_actions", file: inside, apply: true }), ctx)?.block).toBe(true);
		expect(handler(call("lsp", { action: "code_actions", file: inside }), ctx)).toBeUndefined();
		expect(handler(call("lsp", { action: "request", query: "workspace/symbol" }), ctx)).toBeUndefined();
		expect(handler(call("lsp", { action: "diagnostics", file: inside }), ctx)).toBeUndefined();
	});

	test("protects the canonical checkout discovered from a linked worktree cwd", () => {
		const root = gitFixture();
		const linked = path.join(temporaryDirectory(), "linked");
		git(root, ["worktree", "add", "-q", "-b", "linked-branch", linked]);
		const { handler } = createHarness(noEnv);
		const ctx = contextFor(realpathSync(linked));
		expect(handler(call("write", { path: "note.md", content: "x" }), ctx)).toBeUndefined();
		expect(handler(call("write", { path: path.join(root, "note.md"), content: "x" }), ctx)?.block).toBe(true);
	});

	test("retains the launch protected root when cwd leaves Git", () => {
		const root = gitFixture();
		const { handler } = createHarness({ protectedRoot: root, scratchRoot: null, inheritedWip: null });
		const ctx = contextFor(temporaryDirectory());
		expect(handler(call("write", { path: path.join(root, "note.md"), content: "x" }), ctx)?.block).toBe(true);
		expect(handler(call("write", { path: "note.md", content: "x" }), ctx)).toBeUndefined();
	});

	test("retains a canonical root discovered before the cwd leaves its repository", () => {
		const root = gitFixture();
		const { handler } = createHarness(noEnv);
		expect(handler(call("read", { path: "tracked.txt" }), contextFor(root))).toBeUndefined();

		const outside = temporaryDirectory();
		expect(handler(call("write", { path: path.join(root, "note.md"), content: "x" }), contextFor(outside))?.block).toBe(
			true,
		);
		expect(handler(call("write", { path: "note.md", content: "x" }), contextFor(outside))).toBeUndefined();
	});

	test("uses canonical roots discovered by another workspace handler", () => {
		const root = gitFixture();
		const repos = new RepositoryCache();
		repos.identify(root);
		const { handler } = createHarness(noEnv, repos);

		const outside = temporaryDirectory();
		expect(handler(call("write", { path: path.join(root, "note.md"), content: "x" }), contextFor(outside))?.block).toBe(
			true,
		);
	});

	test("permits everything outside any Git repository without a launch root", () => {
		const { handler } = createHarness(noEnv);
		const ctx = contextFor(temporaryDirectory());
		expect(handler(call("write", { path: "note.md", content: "x" }), ctx)).toBeUndefined();
	});
});
