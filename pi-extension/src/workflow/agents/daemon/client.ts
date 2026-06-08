import { type ChildProcess, type SpawnOptions, spawn } from "node:child_process";
import * as fs from "node:fs";
import * as http from "node:http";
import WebSocket, { type RawData } from "ws";
import {
	decodeFrame,
	type ErrorFrame,
	encodeFrame,
	type Frame,
	PROTOCOL_VERSION,
	type RegisteredFrame,
	type RegisterFrame,
} from "./frames.ts";
import { type DaemonPaths, ensureDaemonRuntimeDir, resolveDaemonPaths } from "./paths.ts";

export interface HealthPingOk {
	ok: true;
	protocol: number;
}

export interface HealthPingFail {
	ok: false;
}

export type HealthPingResult = HealthPingOk | HealthPingFail;

type SpawnLike = (command: string, args: readonly string[], options: SpawnOptions) => ChildProcess;

export interface EnsureDaemonOptions {
	healthPingFn?: (socketPath: string, timeoutMs: number) => Promise<HealthPingResult>;
	spawnFn?: SpawnLike;
	resolvePathsFn?: () => DaemonPaths;
	nowFn?: () => number;
	sleepFn?: (ms: number) => Promise<void>;
	pidExistsFn?: (pid: number) => boolean;
	startupTimeoutMs?: number;
	healthTimeoutMs?: number;
	lockStaleAfterMs?: number;
	lockRetryMs?: number;
}

export interface DaemonIdentity {
	node_id: string;
	role: "session" | "agent";
	parent_id: string | null;
	sibling_group: string | null;
	depth: number;
	session_name: string;
	cwd: string;
}

export interface ConnectOptions {
	socketPath?: string;
	resolvePathsFn?: () => DaemonPaths;
	webSocketFactory?: (url: string) => WebSocket;
}

export interface DaemonConnection {
	send: (frame: Frame) => void;
	on: <T extends Frame["type"]>(type: T, handler: (frame: Extract<Frame, { type: T }>) => void) => () => void;
	onClose: (handler: (code: number, reason: string) => void) => () => void;
	close: () => void;
}

interface SpawnLockContents {
	pid: number;
	ts: number;
}

const DEFAULT_STARTUP_TIMEOUT_MS = 5_000;
const DEFAULT_HEALTH_TIMEOUT_MS = 400;
const DEFAULT_LOCK_STALE_AFTER_MS = 30_000;
const DEFAULT_LOCK_RETRY_MS = 100;

function defaultSleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function defaultPidExists(pid: number): boolean {
	if (!Number.isInteger(pid) || pid <= 0) return false;
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

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
	try {
		await file?.close();
	} catch {
		// best effort
	}
	try {
		await fs.promises.unlink(lockPath);
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

export function spawnDaemonProcess(socketPath: string, spawnFn: SpawnLike = spawn): void {
	const child = spawnFn("basecamp", ["daemon", "--uds", socketPath], {
		detached: true,
		stdio: "ignore",
	});
	child.unref();
}

export async function healthPing(socketPath: string, timeoutMs: number): Promise<HealthPingResult> {
	return await new Promise((resolve) => {
		const req = http.request(
			{
				socketPath,
				path: "/health",
				method: "GET",
				timeout: timeoutMs,
			},
			(res) => {
				let body = "";
				res.setEncoding("utf8");
				res.on("data", (chunk) => {
					body += chunk;
				});
				res.on("end", () => {
					if (res.statusCode !== 200) {
						resolve({ ok: false });
						return;
					}
					try {
						const parsed: unknown = JSON.parse(body);
						if (
							parsed &&
							typeof parsed === "object" &&
							(parsed as { status?: unknown }).status === "ok" &&
							typeof (parsed as { protocol?: unknown }).protocol === "number"
						) {
							resolve({ ok: true, protocol: (parsed as { protocol: number }).protocol });
							return;
						}
					} catch {
						// no-op
					}
					resolve({ ok: false });
				});
			},
		);
		req.on("timeout", () => {
			req.destroy();
			resolve({ ok: false });
		});
		req.on("error", () => {
			resolve({ ok: false });
		});
		req.end();
	});
}

export async function ensureDaemon(options: EnsureDaemonOptions = {}): Promise<{ socketPath: string }> {
	const resolvePathsFn = options.resolvePathsFn ?? resolveDaemonPaths;
	const healthPingFn = options.healthPingFn ?? healthPing;
	const spawnFn = options.spawnFn ?? spawn;
	const nowFn = options.nowFn ?? Date.now;
	const sleepFn = options.sleepFn ?? defaultSleep;
	const pidExistsFn = options.pidExistsFn ?? defaultPidExists;
	const startupTimeoutMs = options.startupTimeoutMs ?? DEFAULT_STARTUP_TIMEOUT_MS;
	const healthTimeoutMs = options.healthTimeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
	const lockStaleAfterMs = options.lockStaleAfterMs ?? DEFAULT_LOCK_STALE_AFTER_MS;
	const lockRetryMs = options.lockRetryMs ?? DEFAULT_LOCK_RETRY_MS;

	const paths = resolvePathsFn();
	await ensureDaemonRuntimeDir(paths.runtimeDir);

	const firstPing = await healthPingFn(paths.socketPath, healthTimeoutMs);
	if (firstPing.ok) {
		if (firstPing.protocol !== PROTOCOL_VERSION) {
			throw new Error(
				`basecamp daemon protocol mismatch at ${paths.socketPath}: daemon=${firstPing.protocol}, client=${PROTOCOL_VERSION}.`,
			);
		}
		return { socketPath: paths.socketPath };
	}

	const deadline = nowFn() + startupTimeoutMs;
	let lockFile: fs.promises.FileHandle | null = null;

	try {
		while (nowFn() <= deadline) {
			try {
				lockFile = await writeSpawnLock(paths.spawnLockPath, nowFn());
				spawnDaemonProcess(paths.socketPath, spawnFn);
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
				if (contenderPing.ok) {
					if (contenderPing.protocol !== PROTOCOL_VERSION) {
						throw new Error(
							`basecamp daemon protocol mismatch at ${paths.socketPath}: daemon=${contenderPing.protocol}, client=${PROTOCOL_VERSION}.`,
						);
					}
					return { socketPath: paths.socketPath };
				}
				await sleepFn(lockRetryMs);
			}
		}

		const ping = await pollHealthy(paths.socketPath, deadline, healthTimeoutMs, healthPingFn, sleepFn, lockRetryMs);
		if (!ping.ok) {
			throw new Error(`Timed out waiting for basecamp daemon at ${paths.socketPath}.`);
		}
		if (ping.protocol !== PROTOCOL_VERSION) {
			throw new Error(
				`basecamp daemon protocol mismatch at ${paths.socketPath}: daemon=${ping.protocol}, client=${PROTOCOL_VERSION}.`,
			);
		}

		return { socketPath: paths.socketPath };
	} finally {
		if (lockFile) {
			await releaseSpawnLock(lockFile, paths.spawnLockPath);
		}
	}
}

function rawToFramePayload(data: RawData): string | Buffer {
	if (typeof data === "string" || Buffer.isBuffer(data)) return data;
	if (Array.isArray(data)) {
		return Buffer.concat(data.map((chunk) => (Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))));
	}
	return Buffer.from(data);
}

export async function connect(identity: DaemonIdentity, options: ConnectOptions = {}): Promise<DaemonConnection> {
	const resolvePathsFn = options.resolvePathsFn ?? resolveDaemonPaths;
	const socketPath = options.socketPath ?? resolvePathsFn().socketPath;
	const wsFactory = options.webSocketFactory ?? ((url: string) => new WebSocket(url));
	const ws = wsFactory(`ws+unix://${socketPath}:/ws`);

	const handlers = new Map<Frame["type"], Set<(frame: Frame) => void>>();
	const closeHandlers = new Set<(code: number, reason: string) => void>();

	return await new Promise((resolve, reject) => {
		let settled = false;
		let registered = false;
		let closeCode = 0;
		let closeReason = "";

		const onError = (error: Error) => {
			if (!settled) {
				settled = true;
				reject(error);
			}
		};

		const onClose = (code: number, reasonData: Buffer) => {
			closeCode = code;
			closeReason = reasonData.toString("utf8");
			for (const handler of closeHandlers) {
				handler(closeCode, closeReason);
			}
			if (!settled || !registered) {
				settled = true;
				reject(new Error(`Daemon connection closed (${closeCode}): ${closeReason || "no reason"}`));
			}
		};

		const registerFrame: RegisterFrame = {
			type: "register",
			v: PROTOCOL_VERSION,
			role: identity.role,
			node_id: identity.node_id,
			parent_id: identity.parent_id,
			sibling_group: identity.sibling_group,
			depth: identity.depth,
			session_name: identity.session_name,
			cwd: identity.cwd,
		};

		ws.on("open", () => {
			ws.send(encodeFrame(registerFrame));
		});

		ws.on("message", (raw) => {
			let frame: Frame;
			try {
				frame = decodeFrame(rawToFramePayload(raw));
			} catch (error) {
				onError(error as Error);
				return;
			}

			if (!registered) {
				if (frame.type === "registered") {
					const registeredFrame = frame as RegisteredFrame;
					registered = true;
					if (registeredFrame.protocol !== PROTOCOL_VERSION) {
						onError(
							new Error(
								`Daemon registered with incompatible protocol ${registeredFrame.protocol}; expected ${PROTOCOL_VERSION}.`,
							),
						);
						return;
					}
					if (!settled) {
						settled = true;
						resolve({
							send(outboundFrame) {
								ws.send(encodeFrame(outboundFrame));
							},
							on(type, handler) {
								const set = handlers.get(type) ?? new Set();
								const wrapped = handler as unknown as (frame: Frame) => void;
								set.add(wrapped);
								handlers.set(type, set);
								return () => set.delete(wrapped);
							},
							onClose(handler) {
								closeHandlers.add(handler);
								return () => closeHandlers.delete(handler);
							},
							close() {
								ws.close();
							},
						});
					}
					return;
				}
				if (frame.type === "error") {
					const errorFrame = frame as ErrorFrame;
					onError(new Error(`Daemon registration failed (${errorFrame.code}): ${errorFrame.message}`));
					return;
				}
				return;
			}

			const set = handlers.get(frame.type);
			if (!set || set.size === 0) return;
			for (const handler of set) {
				handler(frame);
			}
		});

		ws.on("error", onError);
		ws.on("close", onClose);
	});
}
