/**
 * Copilot launch seam.
 *
 * `--copilot` is registered by exactly one extension (core/pi's registerSession).
 * `getFlag` is per-extension, so other packages cannot read the flag directly
 * without re-registering it (which would trip the loader's flag-conflict
 * diagnostic). Instead, core exposes the launch value through this reader and
 * consumers read `isCopilotLaunch()`.
 */

type CopilotLaunchReader = () => boolean;

// Wiring, not surviving state: core re-registers the reader on every load.
let copilotLaunchReader: CopilotLaunchReader | null = null;

export function setCopilotLaunchReader(reader: CopilotLaunchReader): void {
	copilotLaunchReader = reader;
}

export function isCopilotLaunch(): boolean {
	try {
		return copilotLaunchReader?.() ?? false;
	} catch {
		return false;
	}
}

export function resetCopilotLaunchForTesting(): void {
	copilotLaunchReader = null;
}
