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
	it("routes destructive push and clean forms to safe_git", async () => {
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

	it("blocks wrapper and nested destructive git forms", async () => {
		for (const command of [
			"command git push --force origin main",
			"env FOO=bar git clean -fd",
			"/usr/bin/git push --delete origin old",
			"bash -c 'git push --force origin main'",
			"zsh -c 'git push origin +main'",
			"xargs git push --mirror origin",
		]) {
			assert.match(await blocked(command), /safe_git/, command);
		}
	});

	it("continues to allow ordinary read-only git through bash", async () => {
		await allowed("git status");
		await allowed("git log --oneline -5");
	});
});
