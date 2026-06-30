import * as fs from "node:fs";
import * as path from "node:path";
import { basecampRoot } from "./paths.ts";

export function readWorktreeSetupCommand(homeDir?: string): string | null {
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

	if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
		return null;
	}

	const command = (parsed as Record<string, unknown>).worktree_setup;
	if (typeof command !== "string") {
		return null;
	}

	const trimmed = command.trim();
	return trimmed ? trimmed : null;
}
