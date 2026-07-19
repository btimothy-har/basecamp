import { execFile } from "node:child_process";
import * as fs from "node:fs";
import type { DaemonPaths } from "./paths.ts";

export type FindDaemonPidFn = (socketPath: string) => Promise<number | null>;
export type KillPidFn = (pid: number, signal: NodeJS.Signals) => void;

const DEFAULT_DAEMON_STOP_TIMEOUT_MS = 2_000;

export function defaultSleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export function defaultPidExists(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

export function defaultKillPid(pid: number, signal: NodeJS.Signals): void {
	process.kill(pid, signal);
}

function parseDaemonPid(raw: string): number | null {
	const value = raw.trim();
	if (!/^\d+$/.test(value)) return null;
	const pid = Number(value);
	return Number.isSafeInteger(pid) && pid > 0 ? pid : null;
}

async function readDaemonPidFile(pidPath: string): Promise<number | null> {
	try {
		return parseDaemonPid(await fs.promises.readFile(pidPath, "utf8"));
	} catch {
		return null;
	}
}

function parsePsLine(line: string): { pid: number; args: string } | null {
	const match = line.match(/^\s*(\d+)\s+(.+)\s*$/);
	if (!match) return null;
	const [, pidText, args] = match;
	if (!pidText || !args) return null;
	const pid = Number(pidText);
	if (!Number.isSafeInteger(pid) || pid <= 0) return null;
	return { pid, args };
}

export function isDaemonCommandForSocket(args: string, socketPath: string): boolean {
	// Match both the current `basecamp hub` command and the legacy `basecamp swarm daemon`
	// form, so a daemon left running under the old command line stays reapable across the rename.
	const hasDaemonCommand = /(?:^|\s)(?:\S*\/)?basecamp\s+(?:swarm\s+daemon|hub)(?:\s|$)/.test(args);
	const hasSocketArg = args.includes(`--uds ${socketPath}`) || args.includes(`--uds=${socketPath}`);
	return hasDaemonCommand && hasSocketArg;
}

async function execFileText(command: string, args: readonly string[]): Promise<string> {
	return await new Promise((resolve, reject) => {
		execFile(command, args, { encoding: "utf8", maxBuffer: 10 * 1024 * 1024 }, (error, stdout) => {
			if (error) {
				reject(error);
				return;
			}
			resolve(String(stdout));
		});
	});
}

export async function findDaemonPidByCommand(socketPath: string): Promise<number | null> {
	let stdout: string;
	try {
		stdout = await execFileText("ps", ["-A", "-o", "pid=,args="]);
	} catch {
		return null;
	}

	for (const line of stdout.split("\n")) {
		const processInfo = parsePsLine(line);
		if (!processInfo || processInfo.pid === process.pid) continue;
		if (isDaemonCommandForSocket(processInfo.args, socketPath)) return processInfo.pid;
	}
	return null;
}

async function isDaemonPidForSocket(pid: number, socketPath: string): Promise<boolean> {
	let stdout: string;
	try {
		stdout = await execFileText("ps", ["-p", String(pid), "-o", "args="]);
	} catch {
		return false;
	}
	return stdout.split("\n").some((line) => isDaemonCommandForSocket(line, socketPath));
}

async function resolveDaemonPid(paths: DaemonPaths, findDaemonPidFn: FindDaemonPidFn): Promise<number | null> {
	const pid = await readDaemonPidFile(paths.pidPath);
	if (pid !== null && pid !== process.pid && (await isDaemonPidForSocket(pid, paths.socketPath))) return pid;
	const discoveredPid = await findDaemonPidFn(paths.socketPath);
	return discoveredPid !== process.pid ? discoveredPid : null;
}

async function unlinkIfExists(path: string): Promise<void> {
	try {
		await fs.promises.unlink(path);
	} catch {}
}

function signalDaemon(pid: number, signal: NodeJS.Signals, killPidFn: KillPidFn): void {
	try {
		killPidFn(pid, signal);
	} catch (error) {
		if ((error as NodeJS.ErrnoException | undefined)?.code !== "ESRCH") throw error;
	}
}

async function waitForPidExit(
	pid: number,
	pidExistsFn: (pid: number) => boolean,
	sleepFn: (ms: number) => Promise<void>,
	pollMs: number,
): Promise<boolean> {
	const delayMs = Math.max(1, pollMs);
	const attempts = Math.max(1, Math.ceil(DEFAULT_DAEMON_STOP_TIMEOUT_MS / delayMs));
	for (let attempt = 0; attempt < attempts; attempt += 1) {
		if (!pidExistsFn(pid)) return true;
		await sleepFn(delayMs);
	}
	return !pidExistsFn(pid);
}

export async function terminateDaemon(
	paths: DaemonPaths,
	findDaemonPidFn: FindDaemonPidFn,
	killPidFn: KillPidFn,
	pidExistsFn: (pid: number) => boolean,
	sleepFn: (ms: number) => Promise<void>,
	pollMs: number,
): Promise<void> {
	const pid = await resolveDaemonPid(paths, findDaemonPidFn);
	if (pid !== null && pidExistsFn(pid)) {
		signalDaemon(pid, "SIGTERM", killPidFn);
		const exited = await waitForPidExit(pid, pidExistsFn, sleepFn, pollMs);
		if (!exited) {
			signalDaemon(pid, "SIGKILL", killPidFn);
			await waitForPidExit(pid, pidExistsFn, sleepFn, pollMs);
		}
	}

	await unlinkIfExists(paths.socketPath);
	await unlinkIfExists(paths.pidPath);
}
