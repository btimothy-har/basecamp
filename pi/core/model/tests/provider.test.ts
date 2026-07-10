import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import { writeModelAliasConfig } from "../aliases.ts";
import { createNativeConfigModelAliasProvider } from "../index.ts";

async function createTempDir(t: TestContext): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-model-alias-provider-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

describe("createNativeConfigModelAliasProvider", () => {
	it("resolves and lists aliases from the latest config on every call", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		const provider = createNativeConfigModelAliasProvider(configPath);

		writeModelAliasConfig({ fast: "provider/first", strong: "provider/strong" }, configPath);

		assert.equal(provider.id, "native-config");
		assert.equal(provider.resolve("fast"), "provider/first");
		assert.deepEqual(provider.list(), [
			{ alias: "fast", model: "provider/first", providerId: "native-config" },
			{ alias: "strong", model: "provider/strong", providerId: "native-config" },
		]);

		writeModelAliasConfig({ fast: "provider/second", tiny: "provider/tiny" }, configPath);

		assert.equal(provider.resolve("fast"), "provider/second");
		assert.equal(provider.resolve("strong"), undefined);
		assert.deepEqual(provider.list(), [
			{ alias: "fast", model: "provider/second", providerId: "native-config" },
			{ alias: "tiny", model: "provider/tiny", providerId: "native-config" },
		]);
	});
});
