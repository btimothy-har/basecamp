/**
 * Copilot launch seam.
 *
 * `--copilot` is registered by exactly one extension (core/pi's registerSession).
 * `getFlag` is per-extension, so other packages cannot read the flag directly
 * without re-registering it (which would trip the loader's flag-conflict
 * diagnostic). Instead, core exposes the launch value through this reader and
 * consumers read `isCopilotLaunch()`.
 *
 * Process-scoped via globalThis so `/reload` preserves the registered reader.
 */

type CopilotLaunchReader = () => boolean;

interface CopilotLaunchState {
	reader: CopilotLaunchReader | null;
}

const copilotLaunchKey = Symbol.for("basecamp.copilotLaunch");

type GlobalWithCopilotLaunch = typeof globalThis & {
	[copilotLaunchKey]?: CopilotLaunchState;
};

function getCopilotLaunchState(): CopilotLaunchState {
	const globalObject = globalThis as GlobalWithCopilotLaunch;
	globalObject[copilotLaunchKey] ??= { reader: null };
	return globalObject[copilotLaunchKey];
}

export function setCopilotLaunchReader(reader: CopilotLaunchReader): void {
	getCopilotLaunchState().reader = reader;
}

export function isCopilotLaunch(): boolean {
	try {
		return getCopilotLaunchState().reader?.() ?? false;
	} catch {
		return false;
	}
}

export function resetCopilotLaunchForTesting(): void {
	getCopilotLaunchState().reader = null;
}
