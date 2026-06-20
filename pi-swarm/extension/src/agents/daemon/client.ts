import { type ChildProcess, execFile, type SpawnOptions, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as http from "node:http";
import WebSocket, { type RawData } from "ws";
import {
	decodeFrame,
	type ErrorFrame,
	encodeFrame,
	type Frame,
	type ListAgentItem,
	PROTOCOL_VERSION,
	type RegisteredFrame,
	type RegisterFrame,
	type WaitResultFrame,
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
type FindDaemonPidFn = (socketPath: string) => Promise<number | null>;
type KillPidFn = (pid: number, signal: NodeJS.Signals) => void;

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
const DEFAULT_DAEMON_STOP_TIMEOUT_MS = 2_000;

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

function defaultKillPid(pid: number, signal: NodeJS.Signals): void {
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

function isDaemonCommandForSocket(args: string, socketPath: string): boolean {
	const hasDaemonCommand = /(?:^|\s)(?:\S*\/)?basecamp\s+swarm\s+daemon(?:\s|$)/.test(args);
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

async function findDaemonPidByCommand(socketPath: string): Promise<number | null> {
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

async function terminateDaemon(
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

export function spawnDaemonProcess(socketPath: string, pidPath: string, spawnFn: SpawnLike = spawn): void {
	const child = spawnFn("basecamp", ["swarm", "daemon", "--uds", socketPath, "--pidfile", pidPath], {
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
				spawnDaemonProcess(paths.socketPath, paths.pidPath, spawnFn);
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
			throw new Error(`Timed out waiting for basecamp swarm daemon at ${paths.socketPath}.`);
		}
		if (ping.protocol !== PROTOCOL_VERSION) {
			throw new Error(
				`basecamp swarm daemon protocol mismatch at ${paths.socketPath}: daemon=${ping.protocol}, client=${PROTOCOL_VERSION}.`,
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

interface DaemonDispatchFrameOptions {
	agentId: string;
	argv: string[];
	task: string;
	cwd: string;
	env: Record<string, string>;
	resumePath?: string | null;
}

export interface DaemonDispatchResult {
	status: "spawned" | "rejected";
	reason?: string | null;
}

export interface DaemonClient {
	dispatchAgent(options: DaemonDispatchFrameOptions): Promise<DaemonDispatchResult>;
	listAgents(input: { awaitable?: boolean }): Promise<ListAgentItem[]>;
	waitForAgents(input: {
		agentIds: string[];
		timeoutS: number;
		signal?: AbortSignal;
	}): Promise<WaitResultFrame["results"]>;
}

function waitForFrame<T extends Frame["type"]>(
	connection: DaemonConnection,
	type: T,
	predicate: (frame: Extract<Frame, { type: T }>) => boolean,
	signal?: AbortSignal,
): Promise<Extract<Frame, { type: T }>> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) {
			reject(new Error("aborted"));
			return;
		}

		let offFrame = () => {};
		let offClose = () => {};
		const cleanup = () => {
			offFrame();
			offClose();
			signal?.removeEventListener("abort", onAbort);
		};
		const rejectWith = (error: Error) => {
			cleanup();
			reject(error);
		};
		const onAbort = () => rejectWith(new Error("aborted"));
		const onClose = (code: number, reason: string) => {
			const detail = reason ? `${code}: ${reason}` : String(code);
			rejectWith(new Error(`daemon connection closed before ${type} frame (${detail})`));
		};

		offFrame = connection.on(type, (frame) => {
			const typed = frame as Extract<Frame, { type: T }>;
			if (!predicate(typed)) return;
			cleanup();
			resolve(typed);
		});
		offClose = connection.onClose(onClose);
		signal?.addEventListener("abort", onAbort, { once: true });
	});
}

function sameAsRequested(resultAgentIds: string[], requestedSet: Set<string>): boolean {
	const resultSet = new Set(resultAgentIds);
	if (resultSet.size !== requestedSet.size) return false;
	return [...requestedSet].every((agentId) => resultSet.has(agentId));
}

function dedupeRequestedResults(
	results: WaitResultFrame["results"],
	requested: Set<string>,
): WaitResultFrame["results"] {
	const requestedMap = new Map(
		results.filter((result) => requested.has(result.agent_id)).map((result) => [result.agent_id, result]),
	);
	const deduped: WaitResultFrame["results"] = [];
	for (const agentId of requested) {
		deduped.push(requestedMap.get(agentId) ?? { agent_id: agentId, status: "unknown", result: null, error: null });
	}
	return deduped;
}

export function createDaemonClient(connection: DaemonConnection): DaemonClient {
	return {
		dispatchAgent: async (input) => {
			const runId = randomUUID();
			connection.send({
				type: "dispatch",
				v: PROTOCOL_VERSION,
				run_id: runId,
				agent_id: input.agentId,
				spec: {
					argv: input.argv,
					task: input.task,
					cwd: input.cwd,
					env: input.env,
					resume_path: input.resumePath ?? null,
				},
			});

			const ack = await waitForFrame(connection, "dispatch_ack", (frame) => frame.run_id === runId);
			return {
				status: ack.status,
				reason: ack.reason,
			};
		},
		listAgents: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "list_agents",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				awaitable: Boolean(input.awaitable),
			});
			const frame = await waitForFrame(
				connection,
				"list_agents_result",
				(response) => response.request_id === requestId,
			);
			return frame.agents;
		},
		waitForAgents: async (input) => {
			const requested = new Set(input.agentIds);
			connection.send({
				type: "wait",
				v: PROTOCOL_VERSION,
				agent_ids: input.agentIds,
				mode: "all",
				timeout_s: input.timeoutS,
			});
			const frame = await waitForFrame(
				connection,
				"wait_result",
				(candidate) =>
					sameAsRequested(
						candidate.results.map((result) => result.agent_id),
						requested,
					),
				input.signal,
			);
			return dedupeRequestedResults(frame.results, requested);
		},
	};
}
