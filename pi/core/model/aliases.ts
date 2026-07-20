import * as fs from "node:fs";
import * as os from "node:os";
import { isRecord } from "../host/files.ts";
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

// Lenient by design: skip malformed/empty entries (and take last-write-wins on
// trim-duplicates, matching the Python reader's dict assignment) rather than
// discarding the whole section, so one bad hand-edited alias never hides the
// good ones. Returns null only when the section itself isn't an object.
function normalizeAliases(value: unknown): ConfiguredModelAliases | null {
	if (!isRecord(value)) return null;

	const normalized: ConfiguredModelAliases = {};
	for (const [alias, model] of Object.entries(value)) {
		const trimmedAlias = alias.trim();
		if (trimmedAlias.length === 0 || typeof model !== "string" || model.trim().length === 0) continue;
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
		return { ok: false, error: "model_aliases must be an object mapping aliases to models." };
	}

	return { ok: true, aliases };
}

export function readModelAliasConfig(configPath = defaultModelAliasConfigPath()): ConfiguredModelAliases {
	const result = loadModelAliasConfig(configPath);
	return result.ok ? result.aliases : {};
}
