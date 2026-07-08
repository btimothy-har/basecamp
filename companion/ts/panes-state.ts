import { isCompanionActive as isCompanionActiveCore, setCompanionActive } from "#core/platform/env.ts";
import type { PaneProviderName } from "./pane-provider.ts";

const stateKey = Symbol.for("basecamp.panes");

interface PaneState {
	provider: PaneProviderName | null;
	paneId: string | null;
}

type GlobalWithPanes = typeof globalThis & {
	[stateKey]?: PaneState;
};

export function getPaneState(): PaneState {
	const globalObject = globalThis as GlobalWithPanes;
	globalObject[stateKey] ??= { provider: null, paneId: null };
	globalObject[stateKey].provider ??= null;
	globalObject[stateKey].paneId ??= null;
	return globalObject[stateKey];
}

/** Delegates to pi-core's companion-active flag. */
export function isCompanionActive(): boolean {
	return isCompanionActiveCore();
}

export { setCompanionActive };
