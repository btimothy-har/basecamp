/**
 * Tracker — persistent context widget below the editor.
 *
 * Two fields:
 *   - Goal: set by main agent via update_context tool
 *   - Assumptions: set by main agent via update_context tool
 *
 * State is persisted via appendEntry for session resume.
 */

import type { ToolResultMessage } from "@mariozechner/pi-ai";
import { Type } from "@sinclair/typebox";
import type {
	ExtensionAPI,
	ExtensionContext,
	Theme,
} from "@mariozechner/pi-coding-agent";
import { visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";

// ============================================================================
// Types
// ============================================================================

interface TrackerState {
	goal: string | null;
	assumptions: string[];
}

// ============================================================================
// Widget Rendering
// ============================================================================

function renderWidget(
	state: TrackerState,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	_bold: Theme["bold"],
	width: number,
): string[] {
	const hasContent = state.goal || state.assumptions.length > 0;
	if (!hasContent) return [];

	const inner: string[] = [];
	const boxWidth = Math.min(width, 80);

	if (state.goal) {
		inner.push(`${fg("dim", "Goal")}  ${state.goal}`);
	}
	if (state.assumptions.length > 0) {
		inner.push(fg("dim", "Assumptions"));
		for (const a of state.assumptions) {
			inner.push(`${fg("muted", "•")} ${a}`);
		}
	}

	// Box-draw border
	const contentWidth = boxWidth - 4;
	const top = fg("dim", `╭${"─".repeat(boxWidth - 2)}╮`);
	const bottom = fg("dim", `╰${"─".repeat(boxWidth - 2)}╯`);
	const lines: string[] = [top];
	for (const line of inner) {
		const wrapped = wrapTextWithAnsi(line, contentWidth);
		for (const wl of wrapped) {
			const vw = visibleWidth(wl);
			const pad = Math.max(0, contentWidth - vw);
			lines.push(`${fg("dim", "│")} ${wl}${" ".repeat(pad)} ${fg("dim", "│")}`);
		}
	}
	lines.push(bottom);
	return lines;
}

// ============================================================================
// Registration
// ============================================================================

export function registerTracker(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;
	let state: TrackerState = { goal: null, assumptions: [] };

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		const hasContent = state.goal || state.assumptions.length > 0;
		if (!hasContent) {
			ctx.ui.setWidget("basecamp-tracker", undefined, { placement: "belowEditor" });
			return;
		}

		ctx.ui.setWidget("basecamp-tracker", (_tui, theme) => {
			const fg = theme.fg.bind(theme);
			const bold = theme.bold.bind(theme);
			let cachedLines: string[] | null = null;
			let cachedWidth = 0;

			return {
				invalidate() { cachedLines = null; },
				render(width: number): string[] {
					if (cachedLines && cachedWidth === width) return cachedLines;
					cachedWidth = width;
					cachedLines = renderWidget(state, fg, bold, width);
					return cachedLines;
				},
			};
		}, { placement: "belowEditor" });
	}

	function persistState(): void {
		pi.appendEntry("tracker-state", state);
	}

	// --- Tool: update_context ---
	pi.registerTool({
		name: "update_context",
		label: "Update Context",
		description: "Update the session context tracker with the current goal and assumptions. Call this when starting a new task, when the goal changes, or when assumptions are established or invalidated.",
		promptSnippet: "Update context tracker (goal + assumptions)",
		parameters: Type.Object({
			goal: Type.String({ description: "What success looks like — concrete and verifiable (1 sentence)" }),
			assumptions: Type.Array(Type.String(), { description: "Things being taken as given that could be wrong (2-4 items)" }),
		}),
		async execute(_id, params, _signal, _onUpdate, _ctx) {
			state.goal = params.goal;
			state.assumptions = params.assumptions;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: "Context updated." }],
				details: { goal: params.goal, assumptions: params.assumptions },
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const goal = (args.goal as string) || "...";
			const preview = goal.length > 60 ? `${goal.slice(0, 60)}...` : goal;
			return new Text(
				theme.fg("toolTitle", theme.bold("update_context ")) + theme.fg("dim", preview),
				0, 0,
			);
		},
		renderResult(_result, { isPartial }, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			if (isPartial) return new Text(theme.fg("dim", "..."), 0, 0);
			return new Text(theme.fg("success", "✓") + theme.fg("dim", " context updated"), 0, 0);
		},
	});

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		state = { goal: null, assumptions: [] };

		// Restore from persisted entries
		const entries = sessionCtx.sessionManager.getEntries();
		const trackerEntry = entries
			.filter((e) => e.type === "custom" && (e as { customType?: string }).customType === "tracker-state")
			.pop() as { data?: TrackerState } | undefined;

		if (trackerEntry?.data) {
			if (trackerEntry.data.goal) state.goal = trackerEntry.data.goal;
			if (trackerEntry.data.assumptions) state.assumptions = trackerEntry.data.assumptions;
		}

		// Restore from tool calls in the branch
		for (const entry of sessionCtx.sessionManager.getBranch()) {
			if (entry.type === "message" && entry.message.role === "toolResult") {
				const msg = entry.message as ToolResultMessage;
				if (msg.toolName === "update_context" && msg.details) {
					const d = msg.details as { goal?: string; assumptions?: string[] };
					if (d.goal) state.goal = d.goal;
					if (d.assumptions) state.assumptions = d.assumptions;
				}
			}
		}

		updateWidget();
	});

	// --- before_agent_start: inject context reminder ---
	pi.on("before_agent_start", async (_event, agentCtx) => {
		if (state.goal && agentCtx.hasUI) {
			const lines = [`Current context tracker state:`, `Goal: ${state.goal}`];
			if (state.assumptions.length > 0) {
				lines.push(`Assumptions:\n${state.assumptions.map((a) => `• ${a}`).join("\n")}`);
			}
			lines.push("", "If the goal or assumptions have changed, call `update_context` to update them.");
			pi.sendMessage(
				{
					customType: "tracker-context",
					content: lines.join("\n"),
					display: false,
				},
				{ deliverAs: "steer" },
			);
		}
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		ctx = null;
	});
}
