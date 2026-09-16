import { afterEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import type { ExecOptions, ExecResult } from "@oh-my-pi/pi-coding-agent";
import { detectHunk, type HunkExec, resolveHunkExecutable } from "../hunk-cli.ts";

const tempRoots: string[] = [];
const originalPath = process.env.PATH;

afterEach(() => {
	for (const root of tempRoots.splice(0)) rmSync(root, { recursive: true, force: true });
	if (originalPath === undefined) delete process.env.PATH;
	else process.env.PATH = originalPath;
});

function tempDir(): string {
	const root = mkdtempSync(join(tmpdir(), "omp-diff-hunk-"));
	tempRoots.push(root);
	return root;
}

function createExecutable(directory: string): string {
	mkdirSync(directory, { recursive: true });
	const executable = join(directory, "hunk");
	writeFileSync(executable, "", { mode: 0o755 });
	return executable;
}

function ok(stdout: string): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

function fail(stdout: string, stderr = ""): ExecResult {
	return { code: 1, stdout, stderr, killed: false };
}

function mockPi(handler: (args: string[]) => ExecResult): { pi: HunkExec; calls: unknown[] } {
	const calls: unknown[] = [];
	const pi: HunkExec = {
		exec: (command: string, args: string[], options?: ExecOptions) => {
			calls.push({ command, args, options });
			return Promise.resolve(handler(args));
		},
	};
	return { pi, calls };
}

describe("resolveHunkExecutable", () => {
	test("selects the first executable in PATH rather than a preferred installation", async () => {
		const root = tempDir();
		const first = createExecutable(join(root, "first"));
		createExecutable(join(root, "second"));
		expect(await resolveHunkExecutable([join(root, "first"), join(root, "second")].join(delimiter), root)).toBe(first);
	});

	test("skips missing, non-executable, directory, and dangling-symlink candidates", async () => {
		const root = tempDir();
		mkdirSync(join(root, "a"));
		writeFileSync(join(root, "a", "hunk"), "", { mode: 0o644 });
		mkdirSync(join(root, "b", "hunk"), { recursive: true });
		mkdirSync(join(root, "c"));
		symlinkSync(join(root, "missing"), join(root, "c", "hunk"));
		const winner = createExecutable(join(root, "d"));
		const path = [join(root, "gone"), join(root, "a"), join(root, "b"), join(root, "c"), join(root, "d")].join(
			delimiter,
		);
		expect(await resolveHunkExecutable(path, root)).toBe(winner);
	});

	test("does not invent search directories when PATH is unset", async () => {
		expect(await resolveHunkExecutable(undefined, tempDir())).toBeNull();
	});

	test("preserves a symlink pathname containing spaces and shell metacharacters", async () => {
		const root = tempDir();
		const target = createExecutable(join(root, "real"));
		const aliasDir = join(root, "dir with 'quotes;$()");
		mkdirSync(aliasDir);
		const alias = join(aliasDir, "hunk");
		symlinkSync(target, alias);
		expect(await resolveHunkExecutable(aliasDir, root)).toBe(alias);
	});
});

describe("detectHunk", () => {
	test("pins the executable after probing required patch capabilities", async () => {
		const root = tempDir();
		const executable = createExecutable(join(root, "bin"));
		process.env.PATH = join(root, "bin");
		const { pi, calls } = mockPi((args) =>
			args[0] === "--version" ? ok("0.21.1\n") : ok("--agent-context <path>\n--agent-notes\n"),
		);
		expect(await detectHunk(pi, root)).toEqual({ available: true, binary: { executable, version: "0.21.1" } });
		expect(calls).toEqual([
			{ command: executable, args: ["--version"], options: { cwd: root, timeout: 4000 } },
			{ command: executable, args: ["patch", "--help"], options: { cwd: root, timeout: 4000 } },
		]);
	});

	test("reports an install hint when hunk is not on PATH", async () => {
		process.env.PATH = tempDir();
		const { pi } = mockPi(() => ok("0.21.1"));
		const availability = await detectHunk(pi, tempDir());
		expect(availability.available).toBe(false);
		if (!availability.available) expect(availability.message).toContain("hunk is not on PATH");
	});

	test("reports a failed --version rather than guessing availability", async () => {
		const root = tempDir();
		createExecutable(join(root, "bin"));
		process.env.PATH = join(root, "bin");
		const { pi } = mockPi(() => fail("", "boom"));
		const availability = await detectHunk(pi, root);
		expect(availability.available).toBe(false);
		if (!availability.available) expect(availability.message).toContain("exited with code 1: boom");
	});

	test("reports an empty --version", async () => {
		const root = tempDir();
		createExecutable(join(root, "bin"));
		process.env.PATH = join(root, "bin");
		const { pi } = mockPi(() => ok("\n"));
		const availability = await detectHunk(pi, root);
		expect(availability.available).toBe(false);
		if (!availability.available) expect(availability.message).toContain("returned no version");
	});

	test("rejects Hunk builds without patch-mode agent-note support", async () => {
		const root = tempDir();
		createExecutable(join(root, "bin"));
		process.env.PATH = join(root, "bin");
		const { pi } = mockPi((args) => (args[0] === "--version" ? ok("0.20.0\n") : ok("patch help")));
		const availability = await detectHunk(pi, root);
		expect(availability.available).toBe(false);
		if (!availability.available) expect(availability.message).toContain("lacks the patch-mode agent-note support");
	});
});
