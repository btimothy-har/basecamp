import { processScoped } from "#core/platform/global-registry.ts";
import type { PaneProviderName } from "./pane-provider.ts";

export { isCompanionActive, setCompanionActive } from "#core/platform/env.ts";

interface PaneState {
	provider: PaneProviderName | null;
	paneId: string | null;
}

// Surviving state: the open pane outlives /reload.
export const getPaneState = processScoped<PaneState>("basecamp.panes", () => ({ provider: null, paneId: null }));
