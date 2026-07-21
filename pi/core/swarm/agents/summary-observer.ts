import type { RunSummaryResult } from "./view/summary.ts";

export type RunSummaryListener = (summary: RunSummaryResult | null) => void;

let latestSummary: RunSummaryResult | null = null;
const listeners = new Set<RunSummaryListener>();

export function publishRunSummary(summary: RunSummaryResult | null): void {
	latestSummary = summary;
	for (const listener of listeners) listener(summary);
}

export function observeRunSummary(listener: RunSummaryListener): () => void {
	listeners.add(listener);
	listener(latestSummary);
	return () => listeners.delete(listener);
}
