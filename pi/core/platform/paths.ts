import * as os from "node:os";
import * as path from "node:path";

export interface BasecampCorePaths {
	rootDir: string;
	coreDir: string;
	sessionStateDir: string;
	modelAliasesPath: string;
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
