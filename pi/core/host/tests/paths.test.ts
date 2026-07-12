import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { basecampCorePaths, basecampExtensionRoot, basecampRoot, piRoot } from "../paths.ts";

describe("basecamp path contract", () => {
	it("builds the pi and basecamp roots from a home directory", () => {
		const homeDir = path.join("tmp", "home");

		assert.equal(piRoot(homeDir), path.join(homeDir, ".pi"));
		assert.equal(basecampRoot(homeDir), path.join(homeDir, ".pi", "basecamp"));
	});

	it("builds core bounded-context paths under the basecamp root", () => {
		const homeDir = path.join("tmp", "home");

		assert.deepEqual(basecampCorePaths(homeDir), {
			rootDir: path.join(homeDir, ".pi", "basecamp"),
			coreDir: path.join(homeDir, ".pi", "basecamp", "core"),
			sessionStateDir: path.join(homeDir, ".pi", "basecamp", "core", "session-state"),
			modelAliasesPath: path.join(homeDir, ".pi", "basecamp", "core", "model-aliases.json"),
		});
	});

	it("resolves the extension root to the repo-root package directory", () => {
		const root = basecampExtensionRoot();

		// Must be a real package root (has package.json) that is the repo root,
		// independent of this file's depth. A stray intermediate package.json — or
		// the old fixed-depth `../../../..` resolve — would return a too-narrow or
		// too-wide dir that fails these repo markers, silently breaking the subagent
		// tool allowlist (getBasecampExtensionToolNames).
		assert.ok(fs.existsSync(path.join(root, "package.json")), "extension root has package.json");
		assert.ok(fs.existsSync(path.join(root, "pi", "core", "host", "paths.ts")), "extension root contains the pi tree");
		assert.ok(fs.existsSync(path.join(root, "AGENTS.md")), "extension root is the repo root");
	});
});
