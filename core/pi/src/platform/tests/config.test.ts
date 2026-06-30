import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { readWorktreeSetupCommand } from "../config.ts";

function createHome(t: { after(fn: () => void): void }): string {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-config-home-"));
	t.after(() => fs.rmSync(homeDir, { recursive: true, force: true }));
	return homeDir;
}

function writeConfig(homeDir: string, contents: string): void {
	const configDir = path.join(homeDir, ".pi", "basecamp");
	fs.mkdirSync(configDir, { recursive: true });
	fs.writeFileSync(path.join(configDir, "config.json"), contents);
}

describe("readWorktreeSetupCommand", () => {
	it("returns null when the config file is missing", (t) => {
		const homeDir = createHome(t);

		assert.equal(readWorktreeSetupCommand(homeDir), null);
	});

	it("returns null for corrupt JSON", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, "{");

		assert.equal(readWorktreeSetupCommand(homeDir), null);
	});

	it("returns null for non-object JSON", (t) => {
		const homeDir = createHome(t);

		for (const contents of ["[]", "42"]) {
			writeConfig(homeDir, contents);
			assert.equal(readWorktreeSetupCommand(homeDir), null);
		}
	});

	it("returns null for missing, blank, or whitespace worktree_setup", (t) => {
		const homeDir = createHome(t);

		for (const contents of [
			JSON.stringify({}),
			JSON.stringify({ worktree_setup: "" }),
			JSON.stringify({ worktree_setup: "   " }),
		]) {
			writeConfig(homeDir, contents);
			assert.equal(readWorktreeSetupCommand(homeDir), null);
		}
	});

	it("returns the trimmed worktree_setup command", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, JSON.stringify({ worktree_setup: "  uv sync  " }));

		assert.equal(readWorktreeSetupCommand(homeDir), "uv sync");
	});
});
