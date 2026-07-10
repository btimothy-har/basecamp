/**
 * Shared exec wrapper.
 *
 * Provides a platform seam for commands that should run in the effective
 * session cwd without importing session runtime state directly. The workspace
 * module overrides the default provider during registration.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type CwdProvider = () => string;

// Wiring, not surviving state: the composition root re-registers the provider
// on every load, so plain module state is correct.
let cwdProvider: CwdProvider | null = null;

/** Register or replace the provider used when exec options omit cwd. */
export function registerCwdProvider(provider: CwdProvider): void {
	cwdProvider = provider;
}

function getDefaultCwd(): string {
	return cwdProvider?.() ?? process.cwd();
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
