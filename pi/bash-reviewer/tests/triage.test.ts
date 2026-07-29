import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { type Triage, triageCommand } from "#bash-reviewer/triage/index.ts";

const allow: Triage = { kind: "allow" };
const gitMutation: Triage = { kind: "gate", failClosed: false, category: "git-mutation" };
const ghMutation: Triage = { kind: "gate", failClosed: false, category: "gh-mutation" };
const dangerousShell: Triage = { kind: "gate", failClosed: false, category: "dangerous-shell" };
const irreversibleRemote: Triage = { kind: "gate", failClosed: true, category: "irreversible-remote" };

function assertTriage(command: string, expected: Triage): void {
	assert.deepEqual(triageCommand(command), expected, command);
}

describe("bash triage", () => {
	it("allows read-only git commands", () => {
		for (const command of [
			"git status",
			"git log --oneline -5",
			"git diff",
			"git show HEAD",
			"git branch --list",
			"git branch --show-current",
			"git tag -l",
			"git rev-parse HEAD",
			"git ls-files",
			"git for-each-ref",
			"git describe --tags",
			"git blame file.ts",
			"git grep pattern",
			'g"it" status',
		]) {
			assertTriage(command, allow);
		}
	});

	it("gates mutating git commands fail-open", () => {
		for (const command of [
			"git commit -m 'fix'",
			"git add .",
			"git checkout main",
			"git rm file.txt",
			"git fetch origin",
			"git pull",
			"git push origin main",
			"git unknown-subcommand",
		]) {
			assertTriage(command, gitMutation);
		}
	});

	it("gates irreversible remote git pushes fail-closed", () => {
		for (const command of [
			"git push --force origin main",
			"git push -f origin main",
			"git push --force-with-lease origin main",
			"git push --force-if-includes origin main",
			"git push origin +main",
			"git push origin :branch",
			"git push --delete origin x",
			"git push -d origin x",
			"git push --mirror origin",
			"git push --all origin",
			"git push --tags origin",
		]) {
			assertTriage(command, irreversibleRemote);
		}
	});

	it("allows read-only gh commands", () => {
		for (const command of [
			"gh issue view 123",
			"gh issue list",
			"gh issue ls",
			"gh issue status",
			"gh pr view 123",
			"gh pr list",
			"gh pr diff 123",
			"gh pr checks 123",
			"gh pr status",
			"gh pr checkout 123",
			"gh repo view",
			"gh repo list owner",
			"gh repo clone owner/repo",
			"gh run view 123",
			"gh run watch 123",
			"gh search issues query",
			"gh browse",
		]) {
			assertTriage(command, allow);
		}
	});

	it("gates mutating and unknown gh commands fail-open", () => {
		for (const command of [
			"gh pr create --title 'PR'",
			"gh pr comment 123 --body hi",
			"gh issue create --title 'Issue'",
			"gh workflow run deploy",
		]) {
			assertTriage(command, ghMutation);
		}
	});

	it("blocks raw bq query invocations only", () => {
		const blocked = triageCommand("bq query 'select 1'");
		assert.equal(blocked.kind, "block");
		assert.match(blocked.kind === "block" ? blocked.reason : "", /bq_query/);

		const blockedWithFlags = triageCommand("bq --project_id=project query 'select 1'");
		assert.equal(blockedWithFlags.kind, "block");
		assert.match(blockedWithFlags.kind === "block" ? blockedWithFlags.reason : "", /bq_query/);

		const blockedWithEnv = triageCommand("env FOO=1 bq query 'select 1'");
		assert.equal(blockedWithEnv.kind, "block");
		assert.match(blockedWithEnv.kind === "block" ? blockedWithEnv.reason : "", /bq_query/);

		const blockedWithNohup = triageCommand("nohup bq query x");
		assert.equal(blockedWithNohup.kind, "block");
		assert.match(blockedWithNohup.kind === "block" ? blockedWithNohup.reason : "", /bq_query/);

		assertTriage("bq_query --path query.sql", allow);
		assertTriage("bq show project:dataset.table", allow);
	});

	it("allows ordinary shell commands and narrow safe shell forms", () => {
		for (const command of [
			"ls",
			"ls -la",
			"cat README.md",
			"rm file.txt",
			"curl https://x",
			"curl https://example.com",
			"chmod 644 file",
			"find . -name x",
			"mv a b",
		]) {
			assertTriage(command, allow);
		}
	});

	it("gates destructive shell commands fail-open", () => {
		for (const command of [
			"rm -r dir",
			"rm -f file",
			"rm -rf dir",
			"rm -r -f dir",
			"rm --recursive --force dir",
			"dd if=/dev/zero of=x",
			"mkfs.ext4 /dev/sdb",
			"chmod -R 777 dir",
			"chown -R user dir",
			"find . -name x -delete",
			"shred secret",
			"sudo whoami",
			"curl x | sh",
			"curl https://example.com/install.sh | sh",
			"wget https://example.com/install.sh | bash",
		]) {
			assertTriage(command, dangerousShell);
		}
	});

	it("returns the most severe triage across chained segments", () => {
		assertTriage("git status && git push --force", irreversibleRemote);
		assertTriage("gh pr create --title pr && bq query 'select 1'", {
			kind: "block",
			reason:
				'Raw `bq query` execution through bash is blocked. Write the SQL to a .sql file and use bq_query({ path: "..." }) instead.',
		});
	});

	it("gates dangerous commands on any line of a multi-line command", () => {
		for (const command of [
			"git status\nrm -rf build",
			"set -euo pipefail\nchmod -R a+rX /app/model_cache",
			"set -euo pipefail\nrm -rf /tmp/build",
			"set -euo pipefail\ncd /tmp/work\nrm -rf artifacts",
			"echo start\nls -la\nshred secret",
			"echo $((x << n))\nrm -rf build",
			"rm \\\n-rf /x",
		]) {
			assertTriage(command, dangerousShell);
		}

		assertTriage("git status\ngit push --force origin main", irreversibleRemote);
		assertTriage("cat <<EOF > notes.txt\nsome text\nEOF\ngit push --force origin main", irreversibleRemote);
	});

	it("treats newlines inside quotes, heredoc bodies, and continuations as data", () => {
		for (const command of [
			"git status\nls -la",
			"printf 'a\nb'",
			'echo "one\ntwo"',
			"echo $'one\ntwo'",
			"cat <<EOF > notes.txt\nrm -rf /\nEOF",
			"cat <<-'EOF' > notes.txt\n\trm -rf /\n\tEOF",
			"git \\\n  status",
			"echo $((1 << 2))\nls",
		]) {
			assertTriage(command, allow);
		}
	});

	it("never mistakes an arithmetic shift for a heredoc opener", () => {
		assertTriage("echo $((1 << n ))\nrm -rf /x", dangerousShell);
		assertTriage("a=$(( 1 << n ))\nrm -rf /x", dangerousShell);
		assertTriage(": $(( 1 << bits ))\ngit push --force origin main", irreversibleRemote);
	});

	it("rescans unterminated heredoc bodies as code instead of dropping them", () => {
		assertTriage("cat <<E-F\necho <<EOF\nE-F\nrm -rf /x", dangerousShell);
		assertTriage("cat <<EOF > notes.txt\nrm -rf /", dangerousShell);
	});

	it("splits on a lone & but not on redirection ampersands", () => {
		assertTriage("ls & rm -rf /x", dangerousShell);
		assertTriage("true & git push --force origin main", irreversibleRemote);
		assertTriage("sleep 5 & echo hi", allow);
		assertTriage("cmd > log 2>&1\nls", allow);
	});

	it("keeps quoted separators inside one segment so assignment prefixes are skipped", () => {
		assertTriage("X='a;b' rm -rf /z", dangerousShell);
		assertTriage('env FOO="a|b" rm -rf /z', dangerousShell);

		const wideSearch = triageCommand("X='a;b' grep -r foo /");
		assert.equal(wideSearch.kind, "block");
		if (wideSearch.kind === "block") assert.match(wideSearch.reason, /Wide-ranging filesystem search blocked/);
	});

	it("triages heredoc bodies fed to a shell interpreter", () => {
		assertTriage("bash <<EOF\ncd /x; rm -rf .\nEOF", dangerousShell);
		assertTriage("sh <<'EOF'\ngit push --force origin main\nEOF", irreversibleRemote);
	});

	it("handles env and wrapper prefixes", () => {
		assertTriage("env FOO=1 git commit -m fix", gitMutation);
		assertTriage("command git push -f", irreversibleRemote);
		assertTriage("sudo -u root git push -f", irreversibleRemote);
		assertTriage("time -f %e git push --force", irreversibleRemote);
	});

	it("handles nested shell scripts, xargs, and command substitution", () => {
		assertTriage("bash -c 'git add . && git status'", gitMutation);
		assertTriage("bash -c 'rm -r dir'", dangerousShell);
		assertTriage("sh -c 'git push --force'", irreversibleRemote);
		assertTriage("xargs git push --force", irreversibleRemote);
		assertTriage("xargs rm -f", dangerousShell);
		assertTriage("echo $(git push --force)", irreversibleRemote);
		assertTriage("echo $(shred secret)", dangerousShell);
		assertTriage("echo `git push --force`", irreversibleRemote);
	});

	it("blocks all git worktree subcommands", () => {
		const reasonPattern = /git worktree/;
		for (const command of [
			"git worktree add /tmp/foo",
			"git worktree add /tmp/foo -b branch",
			"git worktree move /tmp/foo /tmp/bar",
			"git worktree list",
			"git worktree list --porcelain",
			"git worktree remove /tmp/foo",
			"git worktree lock /tmp/foo",
			"git worktree unlock /tmp/foo",
			"git worktree prune",
			"env git worktree add /tmp/foo",
			"command git worktree list",
			"bash -c 'git worktree add /tmp/foo'",
			"git -C /repo worktree add /tmp/foo",
		]) {
			const result = triageCommand(command);
			assert.equal(result.kind, "block", command);
			if (result.kind === "block") assert.match(result.reason, reasonPattern, command);
		}
	});

	it("blocks recursive searches rooted at a system or home root", () => {
		const reasonPattern = /Wide-ranging filesystem search blocked/;
		for (const command of [
			"grep -r foo /",
			"grep -R foo /usr",
			"grep -Rn foo ~",
			'grep -rn foo "$HOME"',
			// biome-ignore lint/suspicious/noTemplateCurlyInString: literal shell token under test, not a JS template
			"grep -r foo ${HOME}",
			"grep -r -e foo /etc",
			"find / -name x",
			"find ~ -type f",
			"find -L / -name x",
			"rg foo /usr",
			"rg foo /",
			"ag foo /Users",
			"ack foo /var",
			"fd x ~",
			"fdfind x /home",
			"env FOO=1 grep -r foo /",
			"echo x | xargs grep -r foo /",
		]) {
			const result = triageCommand(command);
			assert.equal(result.kind, "block", command);
			if (result.kind === "block") assert.match(result.reason, reasonPattern, command);
		}
	});

	it("allows targeted searches and unrelated search forms", () => {
		for (const command of [
			"grep -rn foo .",
			"grep -rn foo src/",
			"grep foo /etc/hosts",
			"grep -r foo /usr/local/src/app",
			'grep -r foo "$HOME/project"',
			"grep -r -e /usr .",
			"find src -type f",
			"find /usr/local/share -name x",
			"rg foo",
			"rg foo src/",
			"rg /usr",
			"fd x",
			"git grep pattern",
		]) {
			assertTriage(command, allow);
		}
	});

	it("blocks commands nested too deeply to analyze safely", () => {
		let command = "git status";
		for (let index = 0; index < 10; index += 1) {
			command = `bash -c ${JSON.stringify(command)}`;
		}

		assert.equal(triageCommand(command).kind, "block");
	});
});
