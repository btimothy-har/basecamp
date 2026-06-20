import type { ExtensionAPI, SessionShutdownEvent } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import { getWorkspaceService, getWorkspaceState } from "pi-core/platform/workspace.ts";
import { getPaneState } from "./panes-state.ts";
import { companionSnapshotPath } from "./snapshot.ts";
import {
	buildCompanionCommand,
	buildKillArgs,
	buildRespawnArgs,
	buildSplitArgs,
	parsePaneId,
	shouldCreatePane,
} from "./tmux.ts";

const PANES_WARNING_PREFIX = "panes:";
let didNotifyMissingBasecamp = false;

async function companionAvailable(pi: ExtensionAPI): Promise<boolean> {
	try {
		const result = await exec(pi, "basecamp", ["companion", "--help"]);
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

function subscribeWorktree(pi: ExtensionAPI, snapshotPath: string): void {
	const state = getPaneState();
	if (state.unsubscribeWorkspace) {
		state.unsubscribeWorkspace();
		state.unsubscribeWorkspace = null;
	}

	let respawnGeneration = 0;
	state.unsubscribeWorkspace =
		getWorkspaceService()?.onChange?.(() => {
			const newCwd = resolveCwd();
			if (state.paneId && newCwd !== state.currentCwd) {
				const generation = ++respawnGeneration;
				exec(
					pi,
					"tmux",
					buildRespawnArgs(state.paneId, newCwd, buildCompanionCommand(snapshotPath, newCwd, resolveScratchDir())),
				)
					.then(() => {
						if (generation === respawnGeneration) state.currentCwd = newCwd;
					})
					.catch(() => {});
			}
		}) ?? null;
}

export default function registerPanes(pi: ExtensionAPI): void {
	const state = getPaneState();
	if (state.unsubscribeWorkspace) {
		state.unsubscribeWorkspace();
		state.unsubscribeWorkspace = null;
	}

	pi.on("session_start", async (_event, ctx) => {
		const paneState = getPaneState();
		const targetPane = process.env.TMUX_PANE;
		const shouldCreate = shouldCreatePane({
			tmux: process.env.TMUX,
			tmuxPane: targetPane,
			hasUI: ctx.hasUI,
			agentDepth: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0"),
		});
		if (!shouldCreate) return;

		const sessionId = ctx.sessionManager.getSessionId();
		const snapshotPath = companionSnapshotPath(sessionId);
		const effectiveCwd = resolveCwd();

		if (!paneState.paneId) {
			if (!(await companionAvailable(pi))) {
				if (!didNotifyMissingBasecamp) {
					ctx.ui.notify("panes: basecamp companion unavailable — companion pane disabled", "warning");
					didNotifyMissingBasecamp = true;
				}
				return;
			}

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
				paneState.paneId = parsePaneId(result.stdout);
				paneState.currentCwd = effectiveCwd;
				paneState.currentSnapshot = snapshotPath;
			} catch (err) {
				const message = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`${PANES_WARNING_PREFIX} failed to open pane — ${message}`, "warning");
				return;
			}
		} else if (snapshotPath !== paneState.currentSnapshot || effectiveCwd !== paneState.currentCwd) {
			try {
				await exec(
					pi,
					"tmux",
					buildRespawnArgs(
						paneState.paneId,
						effectiveCwd,
						buildCompanionCommand(snapshotPath, effectiveCwd, resolveScratchDir()),
					),
				);
				paneState.currentCwd = effectiveCwd;
				paneState.currentSnapshot = snapshotPath;
			} catch {
				// best effort
			}
		}

		subscribeWorktree(pi, snapshotPath);
	});

	pi.on("session_shutdown", async (event: SessionShutdownEvent) => {
		if (event.reason !== "quit") return;

		const paneState = getPaneState();
		if (paneState.paneId) {
			try {
				await exec(pi, "tmux", buildKillArgs(paneState.paneId));
			} catch {
				// best effort
			}
		}

		if (paneState.unsubscribeWorkspace) {
			paneState.unsubscribeWorkspace();
		}
		paneState.paneId = null;
		paneState.currentCwd = null;
		paneState.currentSnapshot = null;
		paneState.unsubscribeWorkspace = null;
	});
}
