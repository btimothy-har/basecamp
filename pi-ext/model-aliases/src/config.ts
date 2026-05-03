import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export type ConfiguredModelAliases = Record<string, string>;

interface RawModelAliasConfig {
	version?: unknown;
	aliases?: unknown;
}

export function defaultModelAliasConfigPath(homeDir = os.homedir()): string {
	return path.join(homeDir, ".pi", "model-aliases", "config.json");
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

function parseAliases(value: unknown): ConfiguredModelAliases {
	if (!isRecord(value)) return {};

	const entries = Object.entries(value);
	if (
		entries.some(
			([alias, model]) => alias.trim().length === 0 || typeof model !== "string" || model.trim().length === 0,
		)
	) {
		return {};
	}

	return Object.fromEntries(entries) as ConfiguredModelAliases;
}

export function readModelAliasConfig(configPath = defaultModelAliasConfigPath()): ConfiguredModelAliases {
	try {
		const parsed: unknown = JSON.parse(fs.readFileSync(configPath, "utf8"));
		if (!isRecord(parsed)) return {};

		const config = parsed as RawModelAliasConfig;
		if (config.version !== 1) return {};

		return parseAliases(config.aliases);
	} catch {
		return {};
	}
}
