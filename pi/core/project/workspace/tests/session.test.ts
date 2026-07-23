import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { registerLogseqAllowedRootProvider, shouldReapOnShutdown } from "../session.ts";
import { listWorkspaceAllowedRoots } from "../state.ts";

describe("shouldReapOnShutdown", () => {
	it("reaps only on a top-level quit", () => {
		assert.equal(shouldReapOnShutdown("quit", 0), true);
	});

	it("never reaps for a subagent, even on quit", () => {
		assert.equal(shouldReapOnShutdown("quit", 1), false);
	});

	it("never reaps on reload/new/resume/fork transitions", () => {
		for (const reason of ["reload", "new", "resume", "fork"] as const) {
			assert.equal(shouldReapOnShutdown(reason, 0), false, `reason ${reason} must not reap`);
		}
	});
});

function createHome(t: { after(fn: () => void): void }): string {
	const homeDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-logseq-home-"));
	t.after(() => fs.rmSync(homeDir, { recursive: true, force: true }));
	return homeDir;
}

function writeConfig(homeDir: string, contents: string): void {
	const configDir = path.join(homeDir, ".pi", "basecamp");
	fs.mkdirSync(configDir, { recursive: true });
	fs.writeFileSync(path.join(configDir, "config.json"), contents);
}

describe("registerLogseqAllowedRootProvider", () => {
	it("registers a valid configured graph directory as an allowed root", (t) => {
		const homeDir = createHome(t);
		const graphDir = path.join(homeDir, "logseq", "main");
		fs.mkdirSync(graphDir, { recursive: true });
		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: graphDir } }));

		registerLogseqAllowedRootProvider(homeDir);

		assert.ok(listWorkspaceAllowedRoots().includes(graphDir));
	});

	it("does not return a root for blank, missing, or removed graph directories", (t) => {
		const homeDir = createHome(t);
		const graphDir = path.join(homeDir, "logseq", "main");
		fs.mkdirSync(graphDir, { recursive: true });

		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: graphDir } }));
		registerLogseqAllowedRootProvider(homeDir);
		assert.ok(listWorkspaceAllowedRoots().includes(graphDir));

		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: "   " } }));
		assert.equal(listWorkspaceAllowedRoots().includes(graphDir), false);

		writeConfig(homeDir, JSON.stringify({}));
		assert.equal(listWorkspaceAllowedRoots().includes(graphDir), false);

		writeConfig(homeDir, JSON.stringify({ logseq: { graph_dir: graphDir } }));
		fs.rmSync(graphDir, { recursive: true, force: true });
		assert.equal(listWorkspaceAllowedRoots().includes(graphDir), false);
	});
});
