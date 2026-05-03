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

function autoApproved(command: string) {
	const result = ok(command);
	assert.equal(result.risk.approvalRequired, false, `${command} should not require approval`);
	return result;
}

function approvalRequired(command: string) {
	const result = ok(command);
	assert.equal(result.risk.approvalRequired, true, `${command} should require approval`);
	assert.equal(result.risk.typedConfirmationRequired, true, `${command} should require typed confirmation`);
	return result;
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

	it("rejects output file flags that bypass stdout", () => {
		assert.match(rejected("git diff --output=/tmp/file HEAD"), /Output file flag/);
		assert.match(rejected("git diff -o /tmp/file HEAD"), /Output file flag/);
		assert.match(rejected("git format-patch --output=/tmp/patch HEAD~1"), /Output file flag/);
	});

	it("classifies branch upstream tracking as mutating", () => {
		const setUpstream = ok("git branch --set-upstream-to=origin/main");
		assert.equal(setUpstream.risk.level, "mutating");
		assert.equal(setUpstream.risk.category, "branch-tracking");
		assert.equal(setUpstream.risk.requiresWorktree, true);

		const setUpstreamShort = ok("git branch -u origin/main");
		assert.equal(setUpstreamShort.risk.level, "mutating");
		assert.equal(setUpstreamShort.risk.requiresWorktree, true);

		const unsetUpstream = ok("git branch --unset-upstream");
		assert.equal(unsetUpstream.risk.level, "mutating");
		assert.equal(unsetUpstream.risk.category, "branch-tracking");
		assert.equal(unsetUpstream.risk.requiresWorktree, true);
	});

	it("classifies notes copy as mutating", () => {
		const notesCopy = ok("git notes copy abc123 def456");
		assert.equal(notesCopy.risk.level, "mutating");
		assert.equal(notesCopy.risk.category, "notes-mutation");
		assert.equal(notesCopy.risk.requiresWorktree, true);
	});
});

describe("approval blocklist (only force-push, broad-push, remote-ref-deletion, forced-clean)", () => {
	it("auto-approves read-only, mutating, and non-blocklisted high-risk commands", () => {
		autoApproved("git status");
		autoApproved("git log --oneline -10");
		autoApproved("git diff HEAD~1");
		autoApproved("git add -A");
		autoApproved("git commit -m 'fix: something'");
		autoApproved("git reset --hard HEAD~1");
		autoApproved("git branch -D old");
		autoApproved("git checkout -b feature");
		autoApproved("git merge feature");
		autoApproved("git pull origin main");
		autoApproved("git push origin feature");
		autoApproved("git rebase main");
		autoApproved("git stash drop");
	});

	it("requires approval for force-push category", () => {
		approvalRequired("git push --force origin main");
		approvalRequired("git push -f origin main");
		approvalRequired("git push --force-with-lease origin main");
		approvalRequired("git push origin +main");
	});

	it("requires approval for broad-push category", () => {
		approvalRequired("git push --mirror origin");
		approvalRequired("git push --all origin");
		approvalRequired("git push --tags origin");
	});

	it("requires approval for remote-ref-deletion category", () => {
		approvalRequired("git push --delete origin old");
		approvalRequired("git push -d origin old");
		approvalRequired("git push origin :old");
	});

	it("requires approval for forced-clean category", () => {
		approvalRequired("git clean -fd");
		approvalRequired("git clean --force -d");
		approvalRequired("git clean -fdx");
	});
});
