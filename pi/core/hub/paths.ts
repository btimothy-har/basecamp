import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "../host/paths.ts";

export interface DaemonPaths {
	runtimeDir: string;
	socketPath: string;
	spawnLockPath: string;
	pidPath: string;
	dbPath: string;
	agentsDir: string;
}

export function resolveDaemonPaths(homeDir = os.homedir()): DaemonPaths {
	const runtimeDir = path.join(basecampRoot(homeDir), "swarm");
	return {
		runtimeDir,
		socketPath: path.join(runtimeDir, "daemon.sock"),
		spawnLockPath: path.join(runtimeDir, "daemon.spawn.lock"),
		pidPath: path.join(runtimeDir, "daemon.pid"),
		dbPath: path.join(runtimeDir, "daemon.db"),
		agentsDir: path.join(runtimeDir, "agents"),
	};
}

export async function ensureDaemonRuntimeDir(runtimeDir: string): Promise<void> {
	await fs.promises.mkdir(runtimeDir, { recursive: true, mode: 0o700 });
}
