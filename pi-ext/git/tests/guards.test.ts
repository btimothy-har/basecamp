import assert from "node:assert/strict";
import { before, describe, it } from "node:test";
import { registerGuards } from "../src/guards.ts";

let handler:
	| ((event: { toolName: string; input: { command: string } }) => Promise<{ block: true; reason: string } | undefined>)
	| null = null;

before(() => {
	registerGuards({
		on(name: string, fn: typeof handler) {
			if (name === "tool_call") handler = fn;
		},
	} as never);
	assert.ok(handler);
});

async function blocked(command: string): Promise<string> {
	assert.ok(handler);
	const result = await handler({ toolName: "bash", input: { command } });
	assert.equal(result?.block, true, command);
	return result.reason;
}

async function allowed(command: string): Promise<void> {
	assert.ok(handler);
	const result = await handler({ toolName: "bash", input: { command } });
	assert.equal(result, undefined, command);
}

describe("git bash guards", () => {
	it("blocks direct git commands including read-only", async () => {
		assert.match(await blocked("git status"), /safe_git/);
		assert.match(await blocked("git log --oneline -5"), /safe_git/);
	});

	it("blocks mutating git commands", async () => {
		assert.match(await blocked("git add -A"), /safe_git/);
		assert.match(await blocked("git commit -m 'fix'"), /safe_git/);
	});

	it("blocks destructive push and clean forms", async () => {
		for (const command of [
			"git push --force-with-lease=main origin main",
			"git push -f origin main",
			"git push origin +main",
			"git push --mirror origin",
			"git push --all origin",
			"git push --tags origin",
			"git push -d origin old",
			"git push origin :old",
			"git clean -fd",
		]) {
			assert.match(await blocked(command), /safe_git/, command);
		}
	});

	it("blocks wrappers: command, env, path-qualified", async () => {
		assert.match(await blocked("command git status"), /safe_git/);
		assert.match(await blocked("env FOO=bar git status"), /safe_git/);
		assert.match(await blocked("/usr/bin/git status"), /safe_git/);
		assert.match(await blocked("/opt/homebrew/bin/git log"), /safe_git/);
	});

	it("blocks additional wrappers: time, nice, nohup, sudo, ionice", async () => {
		assert.match(await blocked("time git status"), /safe_git/);
		assert.match(await blocked("time -p git status"), /safe_git/);
		assert.match(await blocked("nice git log"), /safe_git/);
		assert.match(await blocked("nice -n 5 git log"), /safe_git/);
		assert.match(await blocked("nohup git fetch"), /safe_git/);
		assert.match(await blocked("sudo git status"), /safe_git/);
		assert.match(await blocked("sudo -u root git status"), /safe_git/);
		assert.match(await blocked("ionice git gc"), /safe_git/);
	});

	it("blocks quoted command words that normalize to git", async () => {
		assert.match(await blocked('g"it" status'), /safe_git/);
		assert.match(await blocked("g'it' status"), /safe_git/);
		assert.match(await blocked('"git" status'), /safe_git/);
	});

	it("blocks nested shell -c including quoted scripts with &&", async () => {
		assert.match(await blocked("bash -c 'git status'"), /safe_git/);
		assert.match(await blocked("zsh -c 'git log && echo done'"), /safe_git/);
		assert.match(await blocked("sh -c 'git add -A && git commit -m fix'"), /safe_git/);
	});

	it("blocks recursive shell -c nesting", async () => {
		assert.match(await blocked("bash -c 'bash -c \"git status\"'"), /safe_git/);
		assert.match(await blocked("sh -c 'sh -c \"git log\"'"), /safe_git/);
	});

	it("blocks command substitution containing git", async () => {
		assert.match(await blocked("echo $(git status)"), /safe_git/);
		assert.match(await blocked("echo `git log`"), /safe_git/);
		assert.match(await blocked("VAR=$(git rev-parse HEAD)"), /safe_git/);
	});

	it("blocks xargs with git", async () => {
		assert.match(await blocked("xargs git status"), /safe_git/);
		assert.match(await blocked("xargs git push --mirror origin"), /safe_git/);
	});

	it("blocks compound git commands", async () => {
		assert.match(await blocked("git status && git log"), /safe_git/);
		assert.match(await blocked("git add . ; git commit"), /safe_git/);
	});

	it("allows non-git commands", async () => {
		await allowed("ls -la");
		await allowed("cat README.md");
		await allowed("echo hello");
		await allowed("find . -name '*.ts'");
		await allowed("grep -r pattern .");
		await allowed("npm test");
	});

	it("allows commands that mention git in non-executable contexts", async () => {
		await allowed("echo 'commit to git'");
		await allowed("grep -r git .");
		await allowed("cat .gitignore");
	});
});

describe("gh bash guards", () => {
	it("allows read-only gh commands", async () => {
		await allowed("gh issue list");
		await allowed("gh issue view 123");
		await allowed("gh pr list");
		await allowed("gh pr view 456");
		await allowed("gh pr diff 456");
		await allowed("gh repo view");
		await allowed("gh search issues query");
		await allowed("gh browse");
	});

	it("blocks gh pr mutations", async () => {
		assert.match(await blocked("gh pr create --title 'PR'"), /PR mutations.*blocked/);
		assert.match(await blocked("gh pr merge 123"), /PR mutations.*blocked/);
		assert.match(await blocked("gh pr close 123"), /PR mutations.*blocked/);
	});

	it("blocks gh issue mutations", async () => {
		assert.match(await blocked("gh issue create --title 'Issue'"), /Issue mutations.*blocked/);
		assert.match(await blocked("gh issue close 123"), /Issue mutations.*blocked/);
		assert.match(await blocked("gh issue edit 123"), /Issue mutations.*blocked/);
	});

	it("blocks unknown gh commands", async () => {
		assert.match(await blocked("gh workflow run deploy"), /This gh command is blocked/);
		assert.match(await blocked("gh gist create file.txt"), /This gh command is blocked/);
	});
});

describe("bq bash guards", () => {
	it("blocks bq query execution", async () => {
		assert.match(await blocked("bq query 'SELECT 1'"), /bq_query/);
		assert.match(await blocked("bq --project_id=proj query 'SELECT 1'"), /bq_query/);
	});

	it("allows bq non-query commands", async () => {
		await allowed("bq show project:dataset.table");
		await allowed("bq ls");
		await allowed("bq head project:dataset.table");
	});
});
