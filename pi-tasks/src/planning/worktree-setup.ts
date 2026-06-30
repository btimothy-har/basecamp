import type { WorktreeSetupResult } from "pi-core/workspace/setup.ts";

export interface WorktreeSetupSummary {
	ok: boolean;
	exit_code: number;
	timed_out: boolean;
	stderr_tail?: string;
}

export function shouldRunWorktreeSetup(created: boolean, command: string | null): boolean {
	return created && command !== null;
}

export function worktreeSetupSummary(setup: WorktreeSetupResult | null): WorktreeSetupSummary | undefined {
	if (!setup) return undefined;
	return {
		ok: !setup.timedOut && setup.exitCode === 0,
		exit_code: setup.exitCode,
		timed_out: setup.timedOut,
		...(setup.stderrTail ? { stderr_tail: setup.stderrTail } : {}),
	};
}
