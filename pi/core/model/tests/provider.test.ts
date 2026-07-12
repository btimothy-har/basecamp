import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import { createNativeConfigModelAliasProvider } from "../index.ts";

async function createTempDir(t: TestContext): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-model-alias-provider-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

async function writeAliases(configPath: string, aliases: Record<string, string>): Promise<void> {
	await fs.mkdir(path.dirname(configPath), { recursive: true });
	await fs.writeFile(configPath, JSON.stringify({ version: 1, model_aliases: aliases }), "utf8");
}

describe("createNativeConfigModelAliasProvider", () => {
	it("resolves and lists aliases from the latest config on every call", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		const provider = createNativeConfigModelAliasProvider(configPath);

		await writeAliases(configPath, { fast: "provider/first", strong: "provider/strong" });

		assert.equal(provider.id, "native-config");
		assert.equal(provider.resolve("fast"), "provider/first");
		assert.deepEqual(provider.list(), [
			{ alias: "fast", model: "provider/first", providerId: "native-config" },
			{ alias: "strong", model: "provider/strong", providerId: "native-config" },
		]);

		await writeAliases(configPath, { fast: "provider/second", tiny: "provider/tiny" });

		assert.equal(provider.resolve("fast"), "provider/second");
		assert.equal(provider.resolve("strong"), undefined);
		assert.deepEqual(provider.list(), [
			{ alias: "fast", model: "provider/second", providerId: "native-config" },
			{ alias: "tiny", model: "provider/tiny", providerId: "native-config" },
		]);
	});
});
