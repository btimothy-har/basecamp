import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "./paths.ts";

function isPlainObject(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readRootConfig(homeDir: string): Record<string, unknown> | null {
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

	return isPlainObject(parsed) ? parsed : null;
}

function resolveConfiguredPath(value: string, homeDir: string): string {
	if (value === "~") return homeDir;
	if (value.startsWith("~/")) return path.resolve(homeDir, value.slice(2));
	return path.resolve(homeDir, value);
}

export function readWorktreeSetupCommand(repoName: string, homeDir?: string): string | null {
	const parsed = readRootConfig(homeDir ?? os.homedir());
	if (!parsed) return null;

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

export function readLogseqGraphDir(homeDir?: string): string | null {
	const effectiveHomeDir = path.resolve(homeDir ?? os.homedir());
	const parsed = readRootConfig(effectiveHomeDir);
	if (!parsed) return null;

	const logseq = parsed.logseq;
	if (!isPlainObject(logseq)) {
		return null;
	}

	const graphDir = logseq.graph_dir;
	if (typeof graphDir !== "string") {
		return null;
	}

	const trimmed = graphDir.trim();
	if (!trimmed) {
		return null;
	}

	const resolved = resolveConfiguredPath(trimmed, effectiveHomeDir);
	try {
		return fs.statSync(resolved).isDirectory() ? resolved : null;
	} catch {
		return null;
	}
}
