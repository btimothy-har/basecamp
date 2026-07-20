import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { isRecord, readJsonFile } from "./files.ts";
import { basecampConfigPath } from "./paths.ts";

function readRootConfig(homeDir: string): Record<string, unknown> | null {
	const parsed = readJsonFile(basecampConfigPath(homeDir));
	return isRecord(parsed) ? parsed : null;
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
	if (!isRecord(environments)) {
		return null;
	}

	const environment = environments[repoName];
	if (!isRecord(environment)) {
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
	if (!isRecord(logseq)) {
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
