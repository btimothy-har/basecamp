/**
 * Implementation-handoff dispatch — sending the fresh handoff prompt, and the
 * latch that reports a restart is still in flight.
 *
 * The latch exists because `pendingImplementationHandoff` is cleared at the top
 * of the `agent_end` handler while the restart it describes is still pending a
 * macrotask and possibly a whole compaction pass. A peer `agent_end` handler
 * reading that field would conclude no handoff was happening and could fire a
 * competing restart, so the latch stays armed until the prompt is actually sent.
 *
 * Because the latch suppresses that peer for as long as it is armed, a handoff
 * that never completes would disable it for the rest of the session. Compaction
 * awaits an unbounded summarization call, so the compaction path carries a
 * watchdog: a wedged compaction loses its summary, not the handoff.
 */

import {
	buildHandoffCompactionInstructions,
	HANDOFF_COMPACTION_THRESHOLD_PERCENT,
	type PendingImplementationHandoff,
} from "./index.ts";

export interface HandoffLatch {
	readonly active: boolean;
	arm(): void;
	disarm(): void;
}

export function createHandoffLatch(): HandoffLatch {
	let active = false;
	return {
		get active() {
			return active;
		},
		arm() {
			active = true;
		},
		disarm() {
			active = false;
		},
	};
}

export interface CompactRequest {
	customInstructions: string;
	onComplete: () => void;
	onError: () => void;
}

/** A compaction that never reports must strand neither the handoff nor the latch. */
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
