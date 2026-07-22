import { type ChildProcess, type SpawnOptions, spawn } from "node:child_process";
import * as fs from "node:fs";
import { DEFAULT_HEALTH_TIMEOUT_MS, type HealthPingResult, healthPing } from "./http.ts";
import { type DaemonPaths, ensureDaemonRuntimeDir, resolveDaemonPaths } from "./paths.ts";
import {
	defaultKillPid,
	defaultPidExists,
	defaultSleep,
	type FindDaemonPidFn,
	findDaemonPidByCommand,
	type KillPidFn,
	terminateDaemon,
} from "./process.ts";
import { PROTOCOL_VERSION } from "./protocol/index.ts";

type SpawnLike = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;

export interface EnsureDaemonOptions {
	healthPingFn?: (socketPath: string, timeoutMs: number) => Promise<HealthPingResult>;
	spawnFn?: SpawnLike;
	resolvePathsFn?: () => DaemonPaths;
	nowFn?: () => number;
	sleepFn?: (ms: number) => Promise<void>;
	pidExistsFn?: (pid: number) => boolean;
	findDaemonPidFn?: FindDaemonPidFn;
	killPidFn?: KillPidFn;
	startupTimeoutMs?: number;
	healthTimeoutMs?: number;
	lockStaleAfterMs?: number;
	lockRetryMs?: number;
}

interface SpawnLockContents {
	pid: number;
	ts: number;
}

const DEFAULT_STARTUP_TIMEOUT_MS = 5_000;
const DEFAULT_LOCK_STALE_AFTER_MS = 30_000;
const DEFAULT_LOCK_RETRY_MS = 100;

function parseSpawnLock(raw: string): SpawnLockContents | null {
	try {
		const parsed: unknown = JSON.parse(raw);
		if (!parsed || typeof parsed !== "object") return null;
		const record = parsed as Record<string, unknown>;
		if (typeof record.pid !== "number" || typeof record.ts !== "number") return null;
		return { pid: record.pid, ts: record.ts };
	} catch {
		return null;
	}
}

async function isSpawnLockStale(
	lockPath: string,
	nowMs: number,
	staleAfterMs: number,
	pidExists: (pid: number) => boolean,
): Promise<boolean> {
	let raw: string;
	try {
		raw = await fs.promises.readFile(lockPath, "utf8");
	} catch {
		return true;
	}

	const lock = parseSpawnLock(raw);
	if (!lock) return true;
	if (nowMs - lock.ts > staleAfterMs) return true;
	return !pidExists(lock.pid);
}

async function writeSpawnLock(lockPath: string, nowMs: number): Promise<fs.promises.FileHandle> {
	const file = await fs.promises.open(lockPath, "wx", 0o600);
	await file.writeFile(JSON.stringify({ pid: process.pid, ts: nowMs }));
	return file;
}

async function releaseSpawnLock(file: fs.promises.FileHandle | null, lockPath: string): Promise<void> {
	if (!file) return;
	let identity: { dev: number; ino: number } | null = null;
	try {
		const stat = await file.stat();
		identity = { dev: stat.dev, ino: stat.ino };
	} catch {
		// best effort
	}
	try {
		await file.close();
	} catch {
		// best effort
	}
	if (!identity) return;
	try {
		const current = await fs.promises.stat(lockPath);
		if (current.dev === identity.dev && current.ino === identity.ino) {
			await fs.promises.unlink(lockPath);
		}
	} catch {
		// best effort
	}
}

async function pollHealthy(
	socketPath: string,
	deadlineMs: number,
	healthTimeoutMs: number,
	healthPingFn: (socketPath: string, timeoutMs: number) => Promise<HealthPingResult>,
	sleepFn: (ms: number) => Promise<void>,
	lockRetryMs: number,
): Promise<HealthPingResult> {
	while (Date.now() <= deadlineMs) {
		const ping = await healthPingFn(socketPath, healthTimeoutMs);
		if (ping.ok) return ping;
		await sleepFn(lockRetryMs);
	}
	return { ok: false };
}

export function spawnDaemonProcess(
	socketPath: string,
	pidPath: string,
	dbPath: string,
	spawnFn: SpawnLike = spawn,
): void {
	const child = spawnFn("basecamp", ["hub", "--uds", socketPath, "--pidfile", pidPath, "--db", dbPath], {
		detached: true,
		stdio: "ignore",
	});
	child.unref();
}

export async function ensureDaemon(options: EnsureDaemonOptions = {}): Promise<{ socketPath: string }> {
	const resolvePathsFn = options.resolvePathsFn ?? resolveDaemonPaths;
	const healthPingFn = options.healthPingFn ?? healthPing;
	const spawnFn = options.spawnFn ?? spawn;
	const nowFn = options.nowFn ?? Date.now;
	const sleepFn = options.sleepFn ?? defaultSleep;
	const pidExistsFn = options.pidExistsFn ?? defaultPidExists;
	const findDaemonPidFn = options.findDaemonPidFn ?? findDaemonPidByCommand;
	const killPidFn = options.killPidFn ?? defaultKillPid;
	const startupTimeoutMs = options.startupTimeoutMs ?? DEFAULT_STARTUP_TIMEOUT_MS;
	const healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
	const lockStaleAfterMs = options.lockStaleAfterMs ?? DEFAULT_LOCK_STALE_AFTER_MS;
	const lockRetryMs = options.lockRetryMs ?? DEFAULT_LOCK_RETRY_MS;

	const paths = resolvePathsFn();
	await ensureDaemonRuntimeDir(paths.runtimeDir);

	const firstPing = await healthPingFn(paths.socketPath, healthTimeoutMs);
	if (firstPing.ok && firstPing.protocol === PROTOCOL_VERSION) {
		return { socketPath: paths.socketPath };
	}

	const deadline = nowFn() + startupTimeoutMs;
	let lockFile: fs.promises.FileHandle | null = null;

	try {
		while (nowFn() <= deadline) {
			try {
				lockFile = await writeSpawnLock(paths.spawnLockPath, nowFn());
				const lockedPing = await healthPingFn(paths.socketPath, healthTimeoutMs);
				if (lockedPing.ok) {
					if (lockedPing.protocol === PROTOCOL_VERSION) return { socketPath: paths.socketPath };
					await terminateDaemon(paths, findDaemonPidFn, killPidFn, pidExistsFn, sleepFn, lockRetryMs);
				}
				spawnDaemonProcess(paths.socketPath, paths.pidPath, paths.dbPath, spawnFn);
				break;
			} catch (error) {
				const code = (error as NodeJS.ErrnoException | undefined)?.code;
				if (code !== "EEXIST") throw error;

				const stale = await isSpawnLockStale(paths.spawnLockPath, nowFn(), lockStaleAfterMs, pidExistsFn);
				if (stale) {
					try {
						await fs.promises.unlink(paths.spawnLockPath);
					} catch {
						// best effort
					}
					continue;
				}

				const contenderPing = await healthPingFn(paths.socketPath, healthTimeoutMs);
				if (contenderPing.ok && contenderPing.protocol === PROTOCOL_VERSION) {
					return { socketPath: paths.socketPath };
				}
				await sleepFn(lockRetryMs);
			}
		}

		const ping = await pollHealthy(paths.socketPath, deadline, healthTimeoutMs, healthPingFn, sleepFn, lockRetryMs);
		if (!ping.ok) {
			throw new Error(`Timed out waiting for basecamp hub at ${paths.socketPath}.`);
		}
		if (ping.protocol !== PROTOCOL_VERSION) {
			throw new Error(
				`basecamp hub protocol mismatch at ${paths.socketPath}: daemon=${ping.protocol}, client=${PROTOCOL_VERSION}.`,
			);
		}

		return { socketPath: paths.socketPath };
	} finally {
		if (lockFile) {
			await releaseSpawnLock(lockFile, paths.spawnLockPath);
		}
	}
}
