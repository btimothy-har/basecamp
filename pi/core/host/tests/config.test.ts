import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { readLogseqGraphDir, readWorktreeSetupCommand } from "../config.ts";

const REPO = "basecamp";

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

describe("readLogseqGraphDir", () => {
	it("returns null when the config file is missing", (t) => {
		const homeDir = createHome(t);

		assert.equal(readLogseqGraphDir(homeDir), null);
	});

	it("returns null for corrupt JSON", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, "{");

		assert.equal(readLogseqGraphDir(homeDir), null);
	});

	it("returns null for non-object JSON", (t) => {
		const homeDir = createHome(t);

		for (const contents of ["[]", "42"]) {
			writeConfig(homeDir, contents);
			assert.equal(readLogseqGraphDir(homeDir), null);
		}
	});

	it("returns null when logseq is missing or not an object", (t) => {
		const homeDir = createHome(t);

		for (const contents of [
			JSON.stringify({}),
			JSON.stringify({ logseq: null }),
			JSON.stringify({ logseq: [] }),
			JSON.stringify({ logseq: "nope" }),
		]) {
			writeConfig(homeDir, contents);
			assert.equal(readLogseqGraphDir(homeDir), null);
		}
	});

	it("returns null for missing, non-string, blank, or whitespace graph_dir", (t) => {
		const homeDir = createHome(t);

		for (const contents of [
			JSON.stringify({ logseq: {} }),
			JSON.stringify({ logseq: { graph_dir: null } }),
			JSON.stringify({ logseq: { graph_dir: 42 } }),
			JSON.stringify({ logseq: { graph_dir: "" } }),
			JSON.stringify({ logseq: { graph_dir: "   " } }),
		]) {
			writeConfig(homeDir, contents);
			assert.equal(readLogseqGraphDir(homeDir), null);
		}
	});

	it("returns null for a non-existent path", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: path.join(homeDir, "missing") } }));

		assert.equal(readLogseqGraphDir(homeDir), null);
	});

	it("returns null for a non-directory path", (t) => {
		const homeDir = createHome(t);
		const filePath = path.join(homeDir, "graph-file");
		fs.writeFileSync(filePath, "not a directory");
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: filePath } }));

		assert.equal(readLogseqGraphDir(homeDir), null);
	});

	it("returns the trimmed existing directory path", (t) => {
		const homeDir = createHome(t);
		const graphDir = path.join(homeDir, "logseq", "main");
		fs.mkdirSync(graphDir, { recursive: true });
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: `  ${graphDir}  ` } }));

		assert.equal(readLogseqGraphDir(homeDir), graphDir);
	});

	it("expands tilde paths", (t) => {
		const homeDir = createHome(t);
		const graphDir = path.join(homeDir, "logseq", "main");
		fs.mkdirSync(graphDir, { recursive: true });
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: "~/logseq/main" } }));

		assert.equal(readLogseqGraphDir(homeDir), graphDir);

		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: "~" } }));
		assert.equal(readLogseqGraphDir(homeDir), homeDir);
	});

	it("resolves relative paths under home", (t) => {
		const homeDir = createHome(t);
		const graphDir = path.join(homeDir, "logseq", "main");
		fs.mkdirSync(graphDir, { recursive: true });
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: "logseq/main" } }));

		assert.equal(readLogseqGraphDir(homeDir), graphDir);
	});
});

describe("readWorktreeSetupCommand", () => {
	it("returns null when the config file is missing", (t) => {
		const homeDir = createHome(t);

		assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
	});

	it("returns null for corrupt JSON", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, "{");

		assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
	});

	it("returns null for non-object JSON", (t) => {
		const homeDir = createHome(t);

		for (const contents of ["[]", "42"]) {
			writeConfig(homeDir, contents);
			assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
		}
	});

	it("returns null when environments is missing or not an object", (t) => {
		const homeDir = createHome(t);

		for (const contents of [
			JSON.stringify({}),
			JSON.stringify({ environments: null }),
			JSON.stringify({ environments: [] }),
			JSON.stringify({ environments: "nope" }),
		]) {
			writeConfig(homeDir, contents);
			assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
		}
	});

	it("returns null when the repo has no entry", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, JSON.stringify({ environments: { other: { setup: "uv sync" } } }));

		assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
	});

	it("returns null when the environment entry is not an object", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, JSON.stringify({ environments: { basecamp: "uv sync" } }));

		assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
	});

	it("returns null for missing, blank, or whitespace setup", (t) => {
		const homeDir = createHome(t);

		for (const contents of [
			JSON.stringify({ environments: { basecamp: {} } }),
			JSON.stringify({ environments: { basecamp: { setup: "" } } }),
			JSON.stringify({ environments: { basecamp: { setup: "   " } } }),
		]) {
			writeConfig(homeDir, contents);
			assert.equal(readWorktreeSetupCommand(REPO, homeDir), null);
		}
	});

	it("returns the trimmed per-repo setup command", (t) => {
		const homeDir = createHome(t);
		writeConfig(homeDir, JSON.stringify({ environments: { basecamp: { setup: "  uv sync && npm ci  " } } }));

		assert.equal(readWorktreeSetupCommand(REPO, homeDir), "uv sync && npm ci");
	});

	it("resolves the command for the requested repo only", (t) => {
		const homeDir = createHome(t);
		writeConfig(
			homeDir,
			JSON.stringify({
				environments: { basecamp: { setup: "uv sync" }, other: { setup: "npm ci" } },
			}),
		);

		assert.equal(readWorktreeSetupCommand("basecamp", homeDir), "uv sync");
		assert.equal(readWorktreeSetupCommand("other", homeDir), "npm ci");
	});
});
