import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { describe, it, type TestContext } from "node:test";
import { detectHunk, type HunkAvailability, type HunkExec, listHunkSessions, readUserNotes } from "#diff/hunk.ts";
import { resolveHunkExecutable } from "#diff/hunk-executable.ts";

function tempDir(t: TestContext): string {
	const root = mkdtempSync(join(tmpdir(), "basecamp-hunk-"));
	t.after(() => rmSync(root, { recursive: true, force: true }));
	return root;
}

function createExecutable(directory: string): string {
	mkdirSync(directory, { recursive: true });
	const executable = join(directory, "hunk");
	writeFileSync(executable, "", { mode: 0o755 });
	return executable;
}

function usePath(t: TestContext, path: string | undefined): void {
	const original = process.env.PATH;
	t.after(() => {
		if (original === undefined) delete process.env.PATH;
		else process.env.PATH = original;
	});
	if (path === undefined) delete process.env.PATH;
	else process.env.PATH = path;
}

type ExecResult = Awaited<ReturnType<HunkExec["exec"]>>;

function createMockPi(handler: () => ExecResult) {
	const calls: { command: string; args: string[]; options?: Parameters<HunkExec["exec"]>[2] }[] = [];
	const pi: HunkExec = {
		async exec(command, args, options) {
			calls.push({ command, args, options });
			return handler();
		},
	};
	return { pi, calls };
}

function success(stdout: string): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

describe("resolveHunkExecutable", () => {
	it("selects the first executable in PATH rather than a preferred installation", async (t) => {
		const cwd = tempDir(t);
		const first = createExecutable(join(cwd, "pnpm"));
		const second = createExecutable(join(cwd, "native"));
		assert.equal(await resolveHunkExecutable([dirname(first), dirname(second)].join(delimiter), cwd), first);
		assert.equal(await resolveHunkExecutable([dirname(second), dirname(first)].join(delimiter), cwd), second);
	});

	it("skips missing, non-executable, directory, and dangling-symlink candidates", async (t) => {
		const cwd = tempDir(t);
		const nonExecutable = join(cwd, "non-executable");
		mkdirSync(nonExecutable);
		writeFileSync(join(nonExecutable, "hunk"), "", { mode: 0o644 });
		const directory = join(cwd, "directory");
		mkdirSync(join(directory, "hunk"), { recursive: true });
		const dangling = join(cwd, "dangling");
		mkdirSync(dangling);
		symlinkSync(join(cwd, "missing-target"), join(dangling, "hunk"));
		const executable = createExecutable(join(cwd, "valid"));
		const path = [join(cwd, "missing"), nonExecutable, directory, dangling].join(delimiter);
		assert.equal(await resolveHunkExecutable(path, cwd), null);
		assert.equal(await resolveHunkExecutable(`${path}${delimiter}${dirname(executable)}`, cwd), executable);
	});

	it("anchors relative and empty PATH entries to the supplied cwd", async (t) => {
		const cwd = tempDir(t);
		const relative = createExecutable(join(cwd, "tools"));
		const current = createExecutable(cwd);
		assert.equal(await resolveHunkExecutable("tools", cwd), relative);
		assert.equal(await resolveHunkExecutable(".", cwd), current);
		assert.equal(await resolveHunkExecutable("", cwd), current);
		assert.equal(await resolveHunkExecutable(`${delimiter}tools`, cwd), current);
	});

	it("does not invent search directories when PATH is unset", async (t) => {
		const cwd = tempDir(t);
		createExecutable(cwd);
		assert.equal(await resolveHunkExecutable(undefined, cwd), null);
	});

	it("preserves a symlink pathname containing spaces and shell metacharacters", async (t) => {
		const cwd = tempDir(t);
		const target = createExecutable(join(cwd, "target"));
		const directory = join(cwd, "bin with 'quotes;$()`");
		mkdirSync(directory);
		const link = join(directory, "hunk");
		symlinkSync(target, link);
		assert.equal(await resolveHunkExecutable(directory, cwd), link);
	});
});

describe("detectHunk", () => {
	for (const version of ["0.20.1", "0.21.1", "hunk 0.21.1"]) {
		it(`records the reported version ${version} from the first PATH executable`, async (t) => {
			const cwd = tempDir(t);
			const executable = createExecutable(join(cwd, "first 'bin;$()"));
			const alternative = createExecutable(join(cwd, "native"));
			usePath(t, [dirname(executable), dirname(alternative)].join(delimiter));
			const { pi, calls } = createMockPi(() => success(` ${version}\n`));
			assert.deepEqual(await detectHunk(pi, cwd), {
				available: true,
				binary: { executable, version },
			} satisfies HunkAvailability);
			assert.deepEqual(calls, [{ command: executable, args: ["--version"], options: { cwd, timeout: 4000 } }]);
		});
	}

	it("resolves a relative primary PATH once and keeps that executable after PATH changes", async (t) => {
		const cwd = tempDir(t);
		const executable = createExecutable(join(cwd, "tools"));
		usePath(t, "tools");
		let stdout = "0.21.1\n";
		const { pi, calls } = createMockPi(() => success(stdout));
		const availability = await detectHunk(pi, cwd);
		assert.equal(availability.available, true);
		if (!availability.available) return;
		assert.equal(availability.binary.executable, executable);
		process.env.PATH = dirname(createExecutable(join(cwd, "other")));
		stdout = JSON.stringify({ sessions: [], comments: [] });
		assert.deepEqual(await listHunkSessions(pi, availability.binary, cwd), { ok: true, sessions: [] });
		assert.deepEqual(await readUserNotes(pi, availability.binary, "session-id"), { ok: true, notes: [] });
		assert.deepEqual(
			calls.map((call) => call.command),
			[executable, executable, executable],
		);
	});

	it("returns installation guidance without invoking exec when no candidate exists", async (t) => {
		const cwd = tempDir(t);
		usePath(t, join(cwd, "missing"));
		const { pi, calls } = createMockPi(() => {
			throw new Error("must not execute");
		});
		const result = await detectHunk(pi, cwd);
		assert.equal(result.available, false);
		const message = result.available ? "" : result.message;
		assert.match(message, /not on PATH/);
		assert.match(message, /npm i -g hunkdiff/);
		assert.match(message, /brew install hunk/);
		assert.match(message, /Nix/);
		assert.deepEqual(calls, []);
	});

	const failures = [
		{
			name: "nonzero exit",
			result: { ...success("0.20.1"), code: 1, stderr: "auth unavailable\n" },
			error: /code 1: auth unavailable/,
		},
		{
			name: "killed process",
			result: { ...success("0.21.1"), killed: true, stderr: "deadline\n" },
			error: /killed or timed out.*4000.*deadline/,
		},
		{ name: "missing version", result: success(" \n"), error: /returned no version/ },
	];
	for (const { name, result, error } of failures) {
		it(`reports ${name} without trying a later executable`, async (t) => {
			const cwd = tempDir(t);
			const executable = createExecutable(join(cwd, "first"));
			const alternative = createExecutable(join(cwd, "later"));
			usePath(t, [dirname(executable), dirname(alternative)].join(delimiter));
			const { pi, calls } = createMockPi(() => result);
			const availability = await detectHunk(pi, cwd);
			assert.equal(availability.available, false);
			const message = availability.available ? "" : availability.message;
			assert.ok(message.includes(executable));
			assert.match(message, error);
			assert.equal(calls.length, 1);
		});
	}

	it("preserves thrown exec errors without falling back to another binary", async (t) => {
		const cwd = tempDir(t);
		const executable = createExecutable(join(cwd, "first"));
		const alternative = createExecutable(join(cwd, "later"));
		usePath(t, [dirname(executable), dirname(alternative)].join(delimiter));
		const { pi, calls } = createMockPi(() => {
			throw new Error("spawn ENOENT");
		});
		const result = await detectHunk(pi, cwd);
		assert.equal(result.available, false);
		assert.equal(result.available ? "" : result.message, `${executable} --version failed: spawn ENOENT`);
		assert.equal(calls.length, 1);
	});
});
