import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	loadDotenv,
	registerLogseqAllowedRootProvider,
	shouldReapOnShutdown,
} from "#core/project/workspace/session.ts";
import { listWorkspaceAllowedRoots } from "#core/project/workspace/state.ts";

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

describe("loadDotenv", () => {
	it("loads ordinary keys but never BASECAMP_ posture/identity keys", (t) => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-dotenv-"));
		const saved = new Map(
			["BASECAMP_BASH_REVIEWER", "BASECAMP_EXTERNAL_SANDBOX", "DOTENV_TEST_ORDINARY_KEY"].map((key) => [
				key,
				process.env[key],
			]),
		);
		t.after(() => {
			fs.rmSync(root, { recursive: true, force: true });
			for (const [key, value] of saved) {
				if (value === undefined) delete process.env[key];
				else process.env[key] = value;
			}
		});
		for (const key of saved.keys()) delete process.env[key];

		fs.writeFileSync(
			path.join(root, ".env"),
			'BASECAMP_BASH_REVIEWER=off\nBASECAMP_EXTERNAL_SANDBOX=1\nDOTENV_TEST_ORDINARY_KEY="value"\n',
		);

		loadDotenv(root);

		assert.equal(process.env.BASECAMP_BASH_REVIEWER, undefined);
		assert.equal(process.env.BASECAMP_EXTERNAL_SANDBOX, undefined);
		assert.equal(process.env.DOTENV_TEST_ORDINARY_KEY, "value");
	});
});

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
