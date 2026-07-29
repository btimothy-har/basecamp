import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isTriviallySafe } from "#bash-reviewer/fast-path.ts";

function assertSafe(commands: string[]): void {
	for (const command of commands) {
		assert.equal(isTriviallySafe(command), true, `expected trivially safe: ${JSON.stringify(command)}`);
	}
}

function assertGated(commands: string[]): void {
	for (const command of commands) {
		assert.equal(isTriviallySafe(command), false, `expected to reach the gate: ${JSON.stringify(command)}`);
	}
}

describe("isTriviallySafe", () => {
	it("allows read-only executables with literal arguments", () => {
		assertSafe([
			"ls",
			"ls -la",
			"ls -la pi/bash-reviewer",
			"pwd",
			"cat src/file.ts",
			"head -50 pi/bash-reviewer/review.ts",
			"tail -n 20 log.txt",
			"wc -l pi/bash-reviewer/llm.ts",
			"stat pi/extension.ts",
			"file scripts/check-boundaries.ts",
			"which node",
		]);
	});

	it("allows read-only git subcommands", () => {
		assertSafe([
			"git status",
			"git log --oneline -5",
			"git diff",
			"git diff --stat HEAD",
			"git show HEAD",
			"git rev-parse --abbrev-ref HEAD",
			"git ls-files",
			"git blame pi/extension.ts",
		]);
	});

	it("tolerates surrounding and repeated whitespace", () => {
		assertSafe(["  ls -la  ", "git    status", "\tcat file.ts"]);
	});

	it("refuses anything containing a shell metacharacter", () => {
		assertGated([
			"cat f | sh",
			"ls; rm -rf /x",
			"ls && rm -rf build",
			"ls || true",
			"cat $(echo file)",
			"cat `echo file`",
			"ls > out.txt",
			"cat < input.txt",
			"cat file &",
			"(ls)",
			"{ ls; }",
			"cat 'my file.ts'",
			'cat "my file.ts"',
			"ls *.ts",
			"cat file?.ts",
			"cat file[0].ts",
			"cat ~/notes.txt",
			"ls # comment",
			"FOO=bar ls",
			"ls \\\n -la",
			"ls !!",
		]);
	});

	it("refuses a newline even between two read-only commands", () => {
		assertGated(["git status\nls -la", "ls\ncat file.ts"]);
	});

	it("refuses the historical triage bypasses", () => {
		assertGated([
			"echo $(( 1 << 3 ))\nrm -rf /x",
			"X='a;b' rm -rf /z",
			"rm>file -rf /x",
			"bash<<EOF\nrm -rf /x\nEOF",
			"< /dev/null rm -rf /x",
		]);
	});

	it("refuses executables that are not on the read-only allowlist", () => {
		assertGated([
			"rm -rf build",
			"sudo ls",
			"echo hello",
			"date",
			"date -s 2020-01-01",
			"cp a b",
			"mv a b",
			"touch newfile",
			"chmod -R 777 .",
		]);
	});

	it("refuses search tools so the gate keeps judging scope", () => {
		assertGated([
			"grep -r pattern .",
			"egrep -r pattern .",
			"rg pattern",
			"find . -name file.ts",
			"fd pattern",
			"ag pattern",
			"ack pattern",
		]);
	});

	it("refuses interpreters and build tools", () => {
		assertGated([
			"npm test",
			"npm run check",
			"node --version",
			"python script.py",
			"uv run pytest",
			"make lint",
			"npx tsc",
			"bash script.sh",
			"sh -c ls",
		]);
	});

	it("refuses mutating git subcommands", () => {
		assertGated([
			"git commit -m fix",
			"git add .",
			"git push",
			"git push --force",
			"git checkout main",
			"git reset --hard HEAD",
			"git branch -D feature",
			"git tag v1.0.0",
			"git worktree list",
			"git stash",
			"git clean -fd",
		]);
	});

	it("refuses git subcommands that write despite reading like queries", () => {
		assertGated(["git bugreport", "git diagnose", "git fsck", "git fsck --lost-found"]);
	});

	it("refuses git without a recognizable subcommand", () => {
		assertGated(["git", "git --version", "git -C /other/repo status", "git --no-pager log"]);
	});

	it("refuses an executable whose path is qualified", () => {
		assertGated(["/bin/ls", "./ls", "bin/cat file.ts"]);
	});

	it("refuses empty and whitespace-only commands", () => {
		assertGated(["", "   ", "\t"]);
	});
});
