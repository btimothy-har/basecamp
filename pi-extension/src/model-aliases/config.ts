import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export type ConfiguredModelAliases = Record<string, string>;

interface RawModelAliasConfig {
	version?: unknown;
	aliases?: unknown;
}

export type ModelAliasConfigLoadResult = { ok: true; aliases: ConfiguredModelAliases } | { ok: false; error: string };

export function defaultModelAliasConfigPath(homeDir = os.homedir()): string {
	return path.join(homeDir, ".pi", "model-aliases", "config.json");
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeAliases(value: unknown): ConfiguredModelAliases | null {
	if (!isRecord(value)) return null;

	const normalized: ConfiguredModelAliases = {};
	for (const [alias, model] of Object.entries(value)) {
		const trimmedAlias = alias.trim();
		if (trimmedAlias.length === 0 || typeof model !== "string" || model.trim().length === 0) return null;
		if (normalized[trimmedAlias] !== undefined) return null;
		normalized[trimmedAlias] = model.trim();
	}
	return normalized;
}

function validateAliases(aliases: ConfiguredModelAliases): ConfiguredModelAliases {
	const normalized: ConfiguredModelAliases = {};
	for (const [alias, model] of Object.entries(aliases)) {
		const trimmedAlias = alias.trim();
		if (trimmedAlias.length === 0) {
			throw new Error("Model alias keys must be non-empty strings");
		}
		if (typeof model !== "string" || model.trim().length === 0) {
			throw new Error("Model alias values must be non-empty strings");
		}
		if (normalized[trimmedAlias] !== undefined) {
			throw new Error(`Duplicate model alias after trimming: ${trimmedAlias}`);
		}
		normalized[trimmedAlias] = model.trim();
	}
	return normalized;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function isMissingFile(error: unknown): boolean {
	return (
		typeof error === "object" && error !== null && "code" in error && (error as { code?: unknown }).code === "ENOENT"
	);
}

export function loadModelAliasConfig(configPath = defaultModelAliasConfigPath()): ModelAliasConfigLoadResult {
	let raw: string;
	try {
		raw = fs.readFileSync(configPath, "utf8");
	} catch (error) {
		if (isMissingFile(error)) return { ok: true, aliases: {} };
		return { ok: false, error: `Failed to read model alias config: ${errorMessage(error)}` };
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return { ok: false, error: "Model alias config is not valid JSON." };
	}

	if (!isRecord(parsed)) return { ok: false, error: "Model alias config must be a JSON object." };

	const config = parsed as RawModelAliasConfig;
	if (config.version !== 1) return { ok: false, error: "Model alias config version must be 1." };

	const aliases = normalizeAliases(config.aliases);
	if (!aliases) {
		return { ok: false, error: "Model alias config aliases must be non-empty string aliases and models." };
	}

	return { ok: true, aliases };
}

export function readModelAliasConfig(configPath = defaultModelAliasConfigPath()): ConfiguredModelAliases {
	const result = loadModelAliasConfig(configPath);
	return result.ok ? result.aliases : {};
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
