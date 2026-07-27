/**
 * Tabs `/diff` has opened, keyed by worktree.
 *
 * Surviving state, not wiring: a hunk tab outlives the session that opened it,
 * and losing the tab id on /reload would strand a tab nothing can close.
 */

import { processScoped } from "#core/global-registry.ts";

interface OpenTabs {
	byWorktree: Map<string, string>;
}

const getOpenTabs = processScoped<OpenTabs>("basecamp.diffTabs", () => ({ byWorktree: new Map() }));

export function rememberTab(worktreeDir: string, tabId: string): void {
	getOpenTabs().byWorktree.set(worktreeDir, tabId);
}

export function forgetTab(worktreeDir: string): string | undefined {
	const tabs = getOpenTabs().byWorktree;
	const tabId = tabs.get(worktreeDir);
	tabs.delete(worktreeDir);
	return tabId;
}
