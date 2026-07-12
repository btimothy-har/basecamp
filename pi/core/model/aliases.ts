import * as fs from "node:fs";
import * as os from "node:os";
import { basecampConfigPath } from "../host/paths.ts";

export type ConfiguredModelAliases = Record<string, string>;

export type ModelAliasConfigLoadResult = { ok: true; aliases: ConfiguredModelAliases } | { ok: false; error: string };

/**
 * Aliases live in the ``model_aliases`` section of the root config.json.
 * Basecamp (Python) is the sole writer; this module only reads, in-process.
 * The ``/model`` alias TUI mutates via ``basecamp config alias`` (see commands.ts).
 */
export function defaultModelAliasConfigPath(homeDir = os.homedir()): string {
	return basecampConfigPath(homeDir);
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

export function errorMessage(error: unknown): string {
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
		return { ok: false, error: `Failed to read basecamp config: ${errorMessage(error)}` };
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return { ok: false, error: "basecamp config is not valid JSON." };
	}

	if (!isRecord(parsed)) return { ok: false, error: "basecamp config must be a JSON object." };

	const section = parsed.model_aliases;
	if (section === undefined) return { ok: true, aliases: {} };

	const aliases = normalizeAliases(section);
	if (!aliases) {
		return { ok: false, error: "model_aliases must map non-empty alias strings to non-empty model strings." };
	}

	return { ok: true, aliases };
}

export function readModelAliasConfig(configPath = defaultModelAliasConfigPath()): ConfiguredModelAliases {
	const result = loadModelAliasConfig(configPath);
	return result.ok ? result.aliases : {};
}
