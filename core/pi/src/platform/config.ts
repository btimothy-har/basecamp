import * as fs from "node:fs";
import * as path from "node:path";
import { basecampRoot } from "./paths.ts";

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function readWorktreeSetupCommand(repoName: string, homeDir?: string): string | null {
	const configPath = path.join(basecampRoot(homeDir), "config.json");
	let raw: string;
	try {
		raw = fs.readFileSync(configPath, "utf8");
	} catch {
		return null;
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return null;
	}

	if (!isPlainObject(parsed)) {
		return null;
	}

	const environments = parsed.environments;
	if (!isPlainObject(environments)) {
		return null;
	}

	const environment = environments[repoName];
	if (!isPlainObject(environment)) {
		return null;
	}

	const command = environment.setup;
	if (typeof command !== "string") {
		return null;
	}

	const trimmed = command.trim();
	return trimmed ? trimmed : null;
}
