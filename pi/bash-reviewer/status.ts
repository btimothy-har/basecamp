import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

export const REVIEWER_STATUS_ID = "basecamp.bash-reviewer";

/**
 * Render the reviewer's on/off state as a footer status segment.
 *
 * Mirrors `renderDaemonStatus` in `#core/hub/status.ts`: a pure formatter that
 * takes a bound `theme.fg` and returns a themed string, so it is testable
 * without a real UI context.
 */
export function renderReviewerStatus(fg: ThemeFg, paused: boolean): string {
	return paused ? fg("warning", "🛡 off") : fg("success", "🛡 on");
}

/**
 * Publish the reviewer status through `ctx.ui.setStatus` so it appears in the
 * footer's third line alongside other extension statuses (e.g. `swarm ✓`).
 *
 * No-ops when the UI is unavailable, matching `publishDaemonStatus`.
 */
export function publishReviewerStatus(ctx: ExtensionContext, paused: boolean): void {
	if (!ctx.hasUI) return;
	const fg: ThemeFg = (color, text) => ctx.ui.theme.fg(color, text);
	ctx.ui.setStatus(REVIEWER_STATUS_ID, renderReviewerStatus(fg, paused));
}
