import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { readModelAliasConfig } from "../src/config.ts";

async function createTempDir(t: { after(fn: () => Promise<void>): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-model-aliases-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

async function writeConfig(configPath: string, content: unknown): Promise<void> {
	await fs.mkdir(path.dirname(configPath), { recursive: true });
	await fs.writeFile(configPath, JSON.stringify(content), "utf8");
}

describe("readModelAliasConfig", () => {
	it("returns empty aliases when the config file is missing", async (t) => {
		const dir = await createTempDir(t);
		const aliases = readModelAliasConfig(path.join(dir, "missing.json"));

		assert.deepEqual(aliases, {});
	});

	it("returns configured aliases from a valid config", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, {
			version: 1,
			aliases: {
				fast: "anthropic/claude-3-5-haiku-latest",
				strong: "anthropic/claude-sonnet-4-5",
			},
		});

		const aliases = readModelAliasConfig(configPath);

		assert.deepEqual(aliases, {
			fast: "anthropic/claude-3-5-haiku-latest",
			strong: "anthropic/claude-sonnet-4-5",
		});
	});

	it("returns empty aliases for invalid JSON", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await fs.writeFile(configPath, "{ invalid json", "utf8");

		const aliases = readModelAliasConfig(configPath);

		assert.deepEqual(aliases, {});
	});

	it("returns empty aliases for the wrong config version", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { version: 2, aliases: { fast: "provider/model" } });

		const aliases = readModelAliasConfig(configPath);

		assert.deepEqual(aliases, {});
	});

	it("returns empty aliases when aliases are invalid", async (t) => {
		const dir = await createTempDir(t);
		const cases: unknown[] = [
			{ version: 1, aliases: ["fast"] },
			{ version: 1, aliases: { "": "provider/model" } },
			{ version: 1, aliases: { fast: "" } },
			{ version: 1, aliases: { fast: 42 } },
		];

		for (const [index, config] of cases.entries()) {
			const configPath = path.join(dir, `config-${index}.json`);
			await writeConfig(configPath, config);

			assert.deepEqual(readModelAliasConfig(configPath), {});
		}
	});
});
