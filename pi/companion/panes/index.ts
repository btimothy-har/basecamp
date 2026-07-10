import type { ExtensionAPI, ExtensionContext, SessionShutdownEvent } from "@earendil-works/pi-coding-agent";
import { exec } from "#core/host/exec.ts";
import { getWorkspaceEffectiveCwd, getWorkspaceState } from "#core/workspace/service.ts";
import { createHerdrPaneCloser, createHerdrPaneProvider } from "../herdr/provider.ts";
import { companionLiveSnapshotPath } from "../snapshot/model.ts";
import { createTmuxPaneCloser, createTmuxPaneProvider } from "../tmux/provider.ts";
import { buildCompanionCommand } from "./command.ts";
import type { PaneProvider } from "./provider.ts";
import { getPaneState, setCompanionActive } from "./state.ts";

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

function resolveAgentDepth(): number {
	return Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
}

function resolvePaneProvider(ctx: ExtensionContext): PaneProvider | null {
	const agentDepth = resolveAgentDepth();
	return (
		createHerdrPaneProvider({
			herdrEnv: process.env.HERDR_ENV,
			herdrPaneId: process.env.HERDR_PANE_ID,
			herdrSocketPath: process.env.HERDR_SOCKET_PATH,
			hasUI: ctx.hasUI,
			agentDepth,
		}) ??
		createTmuxPaneProvider({
			tmux: process.env.TMUX,
			tmuxPane: process.env.TMUX_PANE,
			hasUI: ctx.hasUI,
			agentDepth,
		})
	);
}

function resolveStoredPaneProvider(providerName: string | null): PaneProvider | null {
	if (providerName === "herdr") return createHerdrPaneCloser();
	if (providerName === "tmux") return createTmuxPaneCloser();
	return null;
}

function resolveCwd(): string {
	return getWorkspaceEffectiveCwd();
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
	state.provider = null;
	state.paneId = null;
	setCompanionActive(false);
	publishPaneStatus(ctx, false);
}

async function reuseExistingPane(pi: ExtensionAPI, provider: PaneProvider, ctx: ExtensionContext): Promise<boolean> {
	const paneState = getPaneState();
	if (!paneState.paneId) return false;
	if (paneState.provider !== provider.name) {
		paneState.provider = null;
		paneState.paneId = null;
		return false;
	}

	if (await provider.paneStillExists(pi, paneState.paneId)) {
		setCompanionActive(true);
		publishPaneStatus(ctx, true);
		return true;
	}

	paneState.provider = null;
	paneState.paneId = null;
	return false;
}

export default function registerPanes(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		const provider = resolvePaneProvider(ctx);
		if (!provider) {
			clearPaneState(ctx);
			return;
		}

		if (await reuseExistingPane(pi, provider, ctx)) return;

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
			const paneId = await provider.createPane(pi, {
				cwd: effectiveCwd,
				command: buildCompanionCommand(snapshotPath, effectiveCwd, resolveScratchDir()),
			});
			if (!paneId) {
				clearPaneState(ctx);
				ctx.ui.notify(`${PANES_WARNING_PREFIX} failed to open pane — ${provider.name} returned no pane id`, "warning");
				return;
			}
			const paneState = getPaneState();
			paneState.provider = provider.name;
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
		const provider = resolveStoredPaneProvider(paneState.provider);
		if (provider && paneState.paneId) {
			try {
				await provider.closePane(pi, paneState.paneId);
			} catch {
				// best effort
			}
		}

		paneState.provider = null;
		paneState.paneId = null;
		setCompanionActive(false);
		clearPaneStatus(ctx);
	});
}
