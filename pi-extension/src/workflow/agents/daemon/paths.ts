import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface DaemonPaths {
	runtimeDir: string;
	socketPath: string;
	spawnLockPath: string;
}

export function resolveDaemonPaths(homeDir = os.homedir()): DaemonPaths {
	const runtimeDir = path.join(homeDir, ".pi", "agent", "basecamp");
	return {
		runtimeDir,
		socketPath: path.join(runtimeDir, "daemon.sock"),
		spawnLockPath: path.join(runtimeDir, "daemon.spawn.lock"),
	};
}

export async function ensureDaemonRuntimeDir(runtimeDir: string): Promise<void> {
	await fs.promises.mkdir(runtimeDir, { recursive: true, mode: 0o700 });
}
