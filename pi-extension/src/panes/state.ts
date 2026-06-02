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

export function isCompanionActive(): boolean {
	return Boolean(getPaneState().paneId);
}
