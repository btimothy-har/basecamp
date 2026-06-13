export type DaemonStatusKind = "idle" | "starting" | "connected" | "unavailable" | "disconnected";

export interface DaemonStatus {
	kind: DaemonStatusKind;
	message?: string;
}

type DaemonStatusListener = (status: DaemonStatus) => void;

interface DaemonStatusRuntime {
	status: DaemonStatus;
	listeners: Set<DaemonStatusListener>;
}

const daemonStatusKey = Symbol.for("basecamp.daemonStatus");

const DEFAULT_DAEMON_STATUS: DaemonStatus = { kind: "idle" };

type GlobalWithDaemonStatus = typeof globalThis & {
	[daemonStatusKey]?: DaemonStatusRuntime;
};

function getDaemonStatusRuntime(): DaemonStatusRuntime {
	const globalObject = globalThis as GlobalWithDaemonStatus;
	globalObject[daemonStatusKey] ??= { status: DEFAULT_DAEMON_STATUS, listeners: new Set() };
	return globalObject[daemonStatusKey];
}

function normalizeStatus(status: DaemonStatus): DaemonStatus {
	const message = status.message?.trim();
	return message ? { kind: status.kind, message } : { kind: status.kind };
}

function sameStatus(left: DaemonStatus, right: DaemonStatus): boolean {
	return left.kind === right.kind && left.message === right.message;
}

export function getDaemonStatus(): DaemonStatus {
	return getDaemonStatusRuntime().status;
}

export function setDaemonStatus(status: DaemonStatus): void {
	const runtime = getDaemonStatusRuntime();
	const next = normalizeStatus(status);
	if (sameStatus(runtime.status, next)) return;
	runtime.status = next;
	for (const listener of runtime.listeners) {
		listener(next);
	}
}

export function onDaemonStatusChange(listener: DaemonStatusListener): () => void {
	const runtime = getDaemonStatusRuntime();
	runtime.listeners.add(listener);
	return () => runtime.listeners.delete(listener);
}

export function resetDaemonStatusForTesting(): void {
	const runtime = getDaemonStatusRuntime();
	runtime.status = DEFAULT_DAEMON_STATUS;
	runtime.listeners.clear();
}
