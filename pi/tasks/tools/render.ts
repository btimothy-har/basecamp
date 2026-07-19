/** Shared tool-result renderers for the tasks context: ✓-success and pending-"..." Text widgets. */

import type { Theme } from "@earendil-works/pi-coding-agent";

export function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

export function renderPartial(theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}
