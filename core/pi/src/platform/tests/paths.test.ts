import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import { basecampCorePaths, basecampRoot, piRoot } from "../paths.ts";

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
});
