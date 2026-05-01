import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseGitCommand } from "../src/safe-git-policy.ts";

function ok(command: string) {
	const result = parseGitCommand(command);
	assert.equal(result.ok, true, result.ok ? undefined : result.reason);
	return result;
}

function rejected(command: string): string {
	const result = parseGitCommand(command);
	assert.equal(result.ok, false, result.ok ? result.command.normalizedCommand : undefined);
	return result.reason;
}

describe("parseGitCommand", () => {
	it("accepts read-only git commands and preserves safe quoted arguments", () => {
		const status = ok("git status");
		assert.equal(status.risk.level, "safe");
		assert.equal(status.risk.requiresWorktree, false);
		assert.deepEqual(status.command.argv, ["git", "status"]);

		const commit = ok("git commit -m 'fix: allow a && b in message'");
		assert.equal(commit.risk.level, "mutating");
		assert.equal(commit.risk.requiresWorktree, true);
		assert.deepEqual(commit.command.argv, ["git", "commit", "-m", "fix: allow a && b in message"]);
	});

	it("rejects shell syntax, wrappers, path-qualified git, and context escapes", () => {
		assert.match(rejected("git status && rm -rf /"), /Shell control syntax/);
		assert.match(rejected("command git status"), /wrapper/);
		assert.match(rejected("/usr/bin/git status"), /path-qualified/);
		assert.match(rejected("git -C /tmp status"), /Global git flag/);
		assert.match(rejected("git --git-dir=/tmp/repo status"), /Global git flag/);
	});

	it("classifies destructive and broad push forms as high risk", () => {
		for (const command of [
			"git push --force-with-lease=main origin main",
			"git push -f origin main",
			"git push origin +main",
			"git push --mirror origin",
			"git push --all origin",
			"git push --tags origin",
		]) {
			const result = ok(command);
			assert.equal(result.risk.level, "high-risk", command);
			assert.equal(result.risk.requiresWorktree, true, command);
			assert.equal(result.risk.typedConfirmationRequired, true, command);
		}
	});

	it("classifies deletion and local destructive forms", () => {
		assert.equal(ok("git push -d origin old").risk.category, "remote-ref-deletion");
		assert.equal(ok("git push origin :old").risk.category, "remote-ref-deletion");
		assert.equal(ok("git clean -fd").risk.category, "forced-clean");
		assert.equal(ok("git reset --hard HEAD~1").risk.category, "working-tree-reset");
		assert.equal(ok("git branch -D old").risk.category, "branch-deletion");
		assert.equal(ok("git tag -d v1").risk.category, "tag-deletion");
	});

	it("does not treat slash branch names as checkout path overwrites", () => {
		const result = ok("git checkout bh/safe-git-tool");
		assert.equal(result.risk.category, "branch-switch");
		assert.equal(result.risk.level, "mutating");
		assert.equal(result.risk.typedConfirmationRequired, false);

		const pathspec = ok("git checkout -- src/file.ts");
		assert.equal(pathspec.risk.category, "checkout-overwrite");
		assert.equal(pathspec.risk.level, "high-risk");
	});

	it("requires a worktree for stash branch and other stash mutations", () => {
		const branch = ok("git stash branch recover-stash");
		assert.equal(branch.risk.category, "stash-branch");
		assert.equal(branch.risk.requiresWorktree, true);

		const list = ok("git stash list");
		assert.equal(list.risk.level, "safe");
		assert.equal(list.risk.requiresWorktree, false);
	});

	it("rejects execution helper and config injection vectors", () => {
		assert.match(rejected("git rebase --exec 'npm test' main"), /execution option/);
		assert.match(rejected("git bisect run npm test"), /executes commands/);
		assert.match(rejected("git submodule foreach 'echo hi'"), /executes commands/);
		assert.match(rejected("git clone -c core.sshCommand=sh origin copy"), /config injection/);
		assert.match(rejected("git clone --upload-pack=/bin/sh origin copy"), /execution option/);
		assert.match(rejected("git grep --open-files-in-pager=less TODO"), /execution option/);
		assert.match(rejected("git config alias.pwn '!rm -rf /'"), /affect command execution/);
		assert.match(rejected("git config core.sshCommand sh"), /affect command execution/);
		assert.match(rejected("git credential fill"), /not allowed/);
		assert.match(rejected("git filter-branch --tree-filter 'rm -rf node_modules'"), /not allowed/);
	});
});
