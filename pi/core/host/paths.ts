import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

export interface BasecampCorePaths {
	rootDir: string;
	coreDir: string;
	sessionStateDir: string;
	modelAliasesPath: string;
}

/**
 * The basecamp extension package root — the directory of the repo-root
 * package.json, since the whole repo is the single Pi package. Used to
 * recognize tools sourced from basecamp itself when building subagent tool
 * allowlists. Resolved by walking up from this module to the nearest
 * package.json, so it is independent of this file's depth in the tree.
 */
export function basecampExtensionRoot(): string {
	const start = path.dirname(fileURLToPath(import.meta.url));
	for (let dir = start; ; ) {
		if (fs.existsSync(path.join(dir, "package.json"))) return dir;
		const parent = path.dirname(dir);
		if (parent === dir) return start;
		dir = parent;
	}
}

export function piRoot(homeDir = os.homedir()): string {
	return path.join(homeDir, ".pi");
}

export function basecampRoot(homeDir = os.homedir()): string {
	return path.join(piRoot(homeDir), "basecamp");
}

export function basecampCorePaths(homeDir = os.homedir()): BasecampCorePaths {
	const rootDir = basecampRoot(homeDir);
	const coreDir = path.join(rootDir, "core");
	return {
		rootDir,
		coreDir,
		sessionStateDir: path.join(coreDir, "session-state"),
		modelAliasesPath: path.join(coreDir, "model-aliases.json"),
	};
}
