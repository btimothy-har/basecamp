/**
 * Implementation-handoff dispatch — sending the fresh handoff prompt.
 *
 * Compaction awaits an unbounded summarization call, and the handoff prompt
 * must not wait on it forever, so the compaction path carries a watchdog:
 * a wedged compaction loses its summary, not the handoff.
 */

import {
	buildHandoffCompactionInstructions,
	HANDOFF_COMPACTION_THRESHOLD_PERCENT,
	type PendingImplementationHandoff,
} from "./index.ts";

export interface CompactRequest {
	customInstructions: string;
	onComplete: () => void;
	onError: () => void;
}

/** A compaction that never reports must not strand the handoff. */
export const COMPACTION_WATCHDOG_MS = 120_000;

function scheduleDefault(fn: () => void, ms: number): () => void {
	const timer = setTimeout(fn, ms);
	return () => clearTimeout(timer);
}

export interface HandoffDispatch {
	handoff: PendingImplementationHandoff;
	/** Nullable because Pi reports unknown context usage as both `null` and `undefined`. */
	contextUsagePercent: number | null | undefined;
	send: () => void;
	compact: (request: CompactRequest) => void;
	/** Returns a cancel function; injectable so tests can fire the watchdog without waiting. */
	schedule?: (fn: () => void, ms: number) => () => void;
}

/**
 * Send the handoff prompt, compacting first when the context is too full to
 * carry it. `send` is invoked at most once: compaction reports completion and
 * failure through separate callbacks, and a compaction that throws outright
 * still has to hand off.
 */
export function dispatchImplementationHandoff(dispatch: HandoffDispatch): void {
	let sent = false;
	const sendOnce = (): void => {
		if (sent) return;
		sent = true;
		dispatch.send();
	};

	const usage = dispatch.contextUsagePercent;
	if (!(typeof usage === "number" && usage > HANDOFF_COMPACTION_THRESHOLD_PERCENT)) {
		sendOnce();
		return;
	}

	let cancelWatchdog = (): void => {};
	const finish = (): void => {
		cancelWatchdog();
		sendOnce();
	};

	try {
		cancelWatchdog = (dispatch.schedule ?? scheduleDefault)(finish, COMPACTION_WATCHDOG_MS);
		dispatch.compact({
			customInstructions: buildHandoffCompactionInstructions(dispatch.handoff),
			onComplete: finish,
			onError: finish,
		});
	} catch {
		finish();
	}
}
