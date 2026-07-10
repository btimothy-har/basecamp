import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { loadModelAliasConfig, readModelAliasConfig, writeModelAliasConfig } from "../aliases.ts";

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

describe("loadModelAliasConfig", () => {
	it("returns ok with empty aliases when the config file is missing", async (t) => {
		const dir = await createTempDir(t);

		const result = loadModelAliasConfig(path.join(dir, "missing.json"));

		assert.deepEqual(result, { ok: true, aliases: {} });
	});

	it("normalizes whitespace around aliases and models", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { version: 1, aliases: { " fast ": " provider/model " } });

		const result = loadModelAliasConfig(configPath);

		assert.deepEqual(result, { ok: true, aliases: { fast: "provider/model" } });
	});

	it("returns an error result for invalid JSON", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await fs.writeFile(configPath, "{ invalid json", "utf8");

		const result = loadModelAliasConfig(configPath);

		assert.deepEqual(result, { ok: false, error: "Model alias config is not valid JSON." });
	});

	it("returns an error result for the wrong config version", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { version: 2, aliases: { fast: "provider/model" } });

		const result = loadModelAliasConfig(configPath);

		assert.deepEqual(result, { ok: false, error: "Model alias config version must be 1." });
	});

	it("returns an error result when aliases are invalid", async (t) => {
		const dir = await createTempDir(t);
		const cases: unknown[] = [
			{ version: 1, aliases: ["fast"] },
			{ version: 1, aliases: { "": "provider/model" } },
			{ version: 1, aliases: { fast: "" } },
			{ version: 1, aliases: { fast: 42 } },
			{ version: 1, aliases: { fast: "provider/fast", " fast ": "provider/other" } },
		];

		for (const [index, config] of cases.entries()) {
			const configPath = path.join(dir, `config-${index}.json`);
			await writeConfig(configPath, config);

			assert.deepEqual(loadModelAliasConfig(configPath), {
				ok: false,
				error: "Model alias config aliases must be non-empty string aliases and models.",
			});
		}
	});
});

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

describe("writeModelAliasConfig", () => {
	it("writes a valid config and creates the parent directory", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "nested", "config.json");

		writeModelAliasConfig(
			{
				" fast ": " anthropic/claude-3-5-haiku-latest ",
				strong: "anthropic/claude-sonnet-4-5",
			},
			configPath,
		);

		const content = JSON.parse(await fs.readFile(configPath, "utf8"));
		assert.deepEqual(content, {
			version: 1,
			aliases: {
				fast: "anthropic/claude-3-5-haiku-latest",
				strong: "anthropic/claude-sonnet-4-5",
			},
		});
		assert.deepEqual(readModelAliasConfig(configPath), {
			fast: "anthropic/claude-3-5-haiku-latest",
			strong: "anthropic/claude-sonnet-4-5",
		});
	});

	it("throws instead of writing invalid aliases", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");

		assert.throws(() => writeModelAliasConfig({ " ": "provider/model" }, configPath));
		assert.throws(() => writeModelAliasConfig({ fast: " " }, configPath));
		assert.throws(() => writeModelAliasConfig({ fast: 42 } as never, configPath));
		assert.equal(await fs.stat(configPath).catch(() => undefined), undefined);
	});

	it("throws when aliases duplicate after trimming", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");

		assert.throws(
			() => writeModelAliasConfig({ fast: "provider/fast", " fast ": "provider/other" }, configPath),
			/Duplicate model alias after trimming: fast/,
		);
		assert.equal(await fs.stat(configPath).catch(() => undefined), undefined);
	});
});
