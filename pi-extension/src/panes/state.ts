const stateKey = Symbol.for("basecamp.panes");

interface PaneState {
	paneId: string | null;
}

type GlobalWithPanes = typeof globalThis & {
	[stateKey]?: PaneState;
};

export function getPaneState(): PaneState {
	const globalObject = globalThis as GlobalWithPanes;
	globalObject[stateKey] ??= { paneId: null };
	return globalObject[stateKey];
}
