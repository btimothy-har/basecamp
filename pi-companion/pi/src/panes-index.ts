import type { ExtensionAPI, ExtensionContext, SessionShutdownEvent } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import { getWorkspaceService, getWorkspaceState } from "pi-core/platform/workspace.ts";
import { getPaneState, setCompanionActive } from "./panes-state.ts";
import { companionLiveSnapshotPath } from "./snapshot.ts";
import { buildCompanionCommand, buildKillArgs, buildSplitArgs, parsePaneId, shouldCreatePane } from "./tmux.ts";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

const PANES_WARNING_PREFIX = "panes:";
const PANE_STATUS_ID = "basecamp.daemon.pane";
let didNotifyMissingBasecamp = false;

async function companionAvailable(pi: ExtensionAPI): Promise<boolean> {
	try {
		const result = await exec(pi, "basecamp", ["companion", "dashboard", "--help"]);
		return result.code === 0;
	} catch {
		return false;
	}
}

function resolveCwd(): string {
	return getWorkspaceService()?.getEffectiveCwd?.() ?? process.cwd();
}

function resolveScratchDir(): string | undefined {
	return getWorkspaceState()?.scratchDir || undefined;
}

function renderPaneStatus(fg: ThemeFg, active: boolean): string {
	return fg(active ? "success" : "muted", active ? "companion ✓" : "companion off");
}

function publishPaneStatus(ctx: ExtensionContext | null, active: boolean): void {
	if (!ctx?.hasUI) return;
	const fg: ThemeFg = (color, text) => ctx.ui.theme.fg(color, text);
	ctx.ui.setStatus(PANE_STATUS_ID, renderPaneStatus(fg, active));
}

function clearPaneStatus(ctx: ExtensionContext | null): void {
	if (!ctx?.hasUI) return;
	ctx.ui.setStatus(PANE_STATUS_ID, undefined);
}

function clearPaneState(ctx: ExtensionContext | null = null): void {
	const state = getPaneState();
	state.paneId = null;
	setCompanionActive(false);
	publishPaneStatus(ctx, false);
}

export default function registerPanes(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		const paneState = getPaneState();
		const targetPane = process.env.TMUX_PANE;
		const shouldCreate = shouldCreatePane({
			tmux: process.env.TMUX,
			tmuxPane: targetPane,
			hasUI: ctx.hasUI,
			agentDepth: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0"),
		});
		if (!shouldCreate) {
			clearPaneState(ctx);
			return;
		}

		if (paneState.paneId) {
			setCompanionActive(true);
			publishPaneStatus(ctx, true);
			return;
		}

		if (!(await companionAvailable(pi))) {
			clearPaneState(ctx);
			if (!didNotifyMissingBasecamp) {
				ctx.ui.notify("panes: basecamp companion unavailable — companion pane disabled", "warning");
				didNotifyMissingBasecamp = true;
			}
			return;
		}

		const snapshotPath = companionLiveSnapshotPath();
		const effectiveCwd = resolveCwd();

		try {
			const result = await exec(
				pi,
				"tmux",
				buildSplitArgs(
					targetPane as string,
					effectiveCwd,
					buildCompanionCommand(snapshotPath, effectiveCwd, resolveScratchDir()),
				),
			);
			const paneId = parsePaneId(result.stdout);
			if (!paneId) {
				clearPaneState(ctx);
				ctx.ui.notify(`${PANES_WARNING_PREFIX} failed to open pane — tmux returned no pane id`, "warning");
				return;
			}
			paneState.paneId = paneId;
			setCompanionActive(true);
			publishPaneStatus(ctx, true);
		} catch (err) {
			clearPaneState(ctx);
			const message = err instanceof Error ? err.message : String(err);
			ctx.ui.notify(`${PANES_WARNING_PREFIX} failed to open pane — ${message}`, "warning");
			return;
		}
	});

	pi.on("session_shutdown", async (event: SessionShutdownEvent, ctx: ExtensionContext) => {
		if (event.reason !== "quit") return;

		const paneState = getPaneState();
		if (paneState.paneId) {
			try {
				await exec(pi, "tmux", buildKillArgs(paneState.paneId));
			} catch {
				// best effort
			}
		}

		paneState.paneId = null;
		setCompanionActive(false);
		clearPaneStatus(ctx);
	});
}
