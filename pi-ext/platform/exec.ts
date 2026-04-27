/**
 * Shared exec wrapper.
 *
 * Provides a platform seam for commands that should run in the effective
 * session cwd without importing core runtime state directly. The cwd provider
 * is process-scoped via globalThis so separate extension entrypoints and
 * `/reload` share one current provider.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

type CwdProvider = () => string;

interface ExecState {
	cwdProvider: CwdProvider | null;
}

const execKey = Symbol.for("basecamp.exec");

type GlobalWithExec = typeof globalThis & {
	[execKey]?: ExecState;
};

function getExecState(): ExecState {
	const globalObject = globalThis as GlobalWithExec;
	globalObject[execKey] ??= { cwdProvider: null };
	return globalObject[execKey];
}

/** Register or replace the provider used when exec options omit cwd. */
export function registerCwdProvider(provider: CwdProvider): void {
	getExecState().cwdProvider = provider;
}

function getDefaultCwd(): string {
	return getExecState().cwdProvider?.() ?? process.cwd();
}

/** Exec a command in options.cwd, the registered cwd, or process.cwd(). */
export function exec(
	pi: ExtensionAPI,
	command: string,
	args: string[],
	options?: Parameters<ExtensionAPI["exec"]>[2],
): ReturnType<ExtensionAPI["exec"]> {
	return pi.exec(command, args, { ...options, cwd: options?.cwd ?? getDefaultCwd() });
}
