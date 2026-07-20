/** Shared tool-result renderers for the tasks context: ✓-success and pending-"..." Text widgets. */

import type { Theme } from "@earendil-works/pi-coding-agent";
import type { TasksRuntime } from "../lifecycle/index.ts";

export function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

export function renderPartial(theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

/** Render the call line for an index-addressed task tool: `<name> [idx] <label preview>`. */
export function renderIndexedTaskCall(toolName: string, args: { task?: unknown }, theme: Theme, runtime: TasksRuntime) {
	const { Text } = require("@earendil-works/pi-tui");
	const idx = args.task as number;
	const label = runtime.state.tasks[idx]?.label ?? "...";
	const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
	return new Text(theme.fg("toolTitle", theme.bold(`${toolName} `)) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
}
