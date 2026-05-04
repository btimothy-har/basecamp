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

function validateAliases(aliases: ConfiguredModelAliases): ConfiguredModelAliases {
	const entries = Object.entries(aliases).map(([alias, model]) => {
		const trimmedAlias = alias.trim();
		if (trimmedAlias.length === 0) {
			throw new Error("Model alias keys must be non-empty strings");
		}
		if (typeof model !== "string" || model.trim().length === 0) {
			throw new Error("Model alias values must be non-empty strings");
		}
		return [trimmedAlias, model.trim()];
	});

	return Object.fromEntries(entries);
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

export function writeModelAliasConfig(
	aliases: ConfiguredModelAliases,
	configPath = defaultModelAliasConfigPath(),
): void {
	const validatedAliases = validateAliases(aliases);
	const configDir = path.dirname(configPath);
	const tmpPath = path.join(configDir, `.config.${process.pid}.${Date.now()}.tmp`);
	const content = `${JSON.stringify({ version: 1, aliases: validatedAliases }, null, 2)}\n`;

	fs.mkdirSync(configDir, { recursive: true });
	try {
		fs.writeFileSync(tmpPath, content, "utf8");
		fs.renameSync(tmpPath, configPath);
	} catch (error) {
		try {
			fs.rmSync(tmpPath, { force: true });
		} catch {
			// Ignore cleanup failures and surface the original write error.
		}
		throw error;
	}
}
