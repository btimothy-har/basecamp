import { isCompanionActive as isCompanionActiveCore, setCompanionActive } from "pi-core/platform/env.ts";

const stateKey = Symbol.for("basecamp.panes");

interface PaneState {
	paneId: string | null;
	currentCwd: string | null;
	currentSnapshot: string | null;
	unsubscribeWorkspace: (() => void) | null;
}

type GlobalWithPanes = typeof globalThis & {
	[stateKey]?: PaneState;
};

export function getPaneState(): PaneState {
	const globalObject = globalThis as GlobalWithPanes;
	globalObject[stateKey] ??= { paneId: null, currentCwd: null, currentSnapshot: null, unsubscribeWorkspace: null };
	return globalObject[stateKey];
}

/** Delegates to pi-core's companion-active flag (read by footer via pi-ui). */
export function isCompanionActive(): boolean {
	return isCompanionActiveCore();
}

export { setCompanionActive };
