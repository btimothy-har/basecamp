import { Buffer } from "node:buffer";
import WebSocket, { type RawData } from "ws";
import { type DaemonPaths, resolveDaemonPaths } from "./paths.ts";
import {
	decodeFrame,
	type ErrorFrame,
	encodeFrame,
	type Frame,
	PROTOCOL_VERSION,
	type RegisteredFrame,
	type RegisterFrame,
} from "./protocol/index.ts";

export interface DaemonIdentity {
	node_id: string;
	agent_handle: string;
	role: "agent" | "worker";
	parent_id: string | null;
	sibling_group: string | null;
	depth: number;
	session_name: string;
	cwd: string;
	session_file?: string | null;
	repo?: string | null;
	worktree_label?: string | null;
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
			agent_handle: identity.agent_handle,
			parent_id: identity.parent_id,
			sibling_group: identity.sibling_group,
			depth: identity.depth,
			session_name: identity.session_name,
			cwd: identity.cwd,
			session_file: identity.session_file ?? null,
			repo: identity.repo ?? null,
			worktree_label: identity.worktree_label ?? null,
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

export function waitForFrame<T extends Frame["type"]>(
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
