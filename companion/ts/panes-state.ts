import { isCompanionActive as isCompanionActiveCore, setCompanionActive } from "#core/platform/env.ts";
import { processScoped } from "#core/platform/global-registry.ts";
import type { PaneProviderName } from "./pane-provider.ts";

interface PaneState {
	provider: PaneProviderName | null;
	paneId: string | null;
}

// Surviving state: the open pane outlives /reload.
export const getPaneState = processScoped<PaneState>("basecamp.panes", () => ({ provider: null, paneId: null }));

/** Delegates to pi-core's companion-active flag. */
export function isCompanionActive(): boolean {
	return isCompanionActiveCore();
}

export { setCompanionActive };
