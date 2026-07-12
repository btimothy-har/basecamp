import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { loadModelAliasConfig, readModelAliasConfig } from "../aliases.ts";

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

	it("returns ok with empty aliases when there is no model_aliases section", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { version: 1, projects: { demo: { repo_root: "src/demo" } } });

		assert.deepEqual(loadModelAliasConfig(configPath), { ok: true, aliases: {} });
	});

	it("normalizes whitespace around aliases and models", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { model_aliases: { " fast ": " provider/model " } });

		const result = loadModelAliasConfig(configPath);

		assert.deepEqual(result, { ok: true, aliases: { fast: "provider/model" } });
	});

	it("returns an error result for invalid JSON", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await fs.writeFile(configPath, "{ invalid json", "utf8");

		assert.deepEqual(loadModelAliasConfig(configPath), {
			ok: false,
			error: "basecamp config is not valid JSON.",
		});
	});

	it("returns an error result when the config is not an object", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, ["not", "an", "object"]);

		assert.deepEqual(loadModelAliasConfig(configPath), {
			ok: false,
			error: "basecamp config must be a JSON object.",
		});
	});

	it("errors only when the section itself is not an object", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { model_aliases: ["fast"] });

		assert.deepEqual(loadModelAliasConfig(configPath), {
			ok: false,
			error: "model_aliases must be an object mapping aliases to models.",
		});
	});

	it("leniently skips malformed entries and takes last-write-wins on trim-duplicates", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, {
			model_aliases: {
				good: "provider/good",
				"": "provider/empty-key",
				blank: "",
				num: 42,
				" good ": "provider/dup",
			},
		});

		// ` good ` trims to `good`, overwriting the earlier value (last-write-wins).
		assert.deepEqual(loadModelAliasConfig(configPath), { ok: true, aliases: { good: "provider/dup" } });
	});
});

describe("readModelAliasConfig", () => {
	it("returns empty aliases when the config file is missing", async (t) => {
		const dir = await createTempDir(t);

		assert.deepEqual(readModelAliasConfig(path.join(dir, "missing.json")), {});
	});

	it("returns configured aliases from a valid section", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, {
			version: 1,
			model_aliases: {
				fast: "anthropic/claude-3-5-haiku-latest",
				strong: "anthropic/claude-sonnet-4-5",
			},
		});

		assert.deepEqual(readModelAliasConfig(configPath), {
			fast: "anthropic/claude-3-5-haiku-latest",
			strong: "anthropic/claude-sonnet-4-5",
		});
	});

	it("returns empty aliases for invalid JSON", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await fs.writeFile(configPath, "{ invalid json", "utf8");

		assert.deepEqual(readModelAliasConfig(configPath), {});
	});

	it("returns empty aliases when the section is not an object", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { model_aliases: ["fast"] });

		assert.deepEqual(readModelAliasConfig(configPath), {});
	});

	it("keeps the good entries and drops the malformed ones", async (t) => {
		const dir = await createTempDir(t);
		const configPath = path.join(dir, "config.json");
		await writeConfig(configPath, { model_aliases: { good: "provider/good", blank: "", num: 42 } });

		assert.deepEqual(readModelAliasConfig(configPath), { good: "provider/good" });
	});
});
