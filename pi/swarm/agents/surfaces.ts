import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { awaitDaemonConnection, deriveDaemonIdentity, onDaemonConnect, resolveDaemonPaths } from "#core/hub/index.ts";
import { resolveModelAlias } from "#core/model/index.ts";
import { getWorkspaceState } from "#core/project/workspace/state.ts";
import { hasInvokedSkill } from "#core/skills/tracker.ts";
import { fetchRunSummary } from "./client.ts";
import { type PeerDeliveryState, registerPeerMessageDeliveryHandler } from "./delivery.ts";
import { basecampExtensionRoot } from "./extension-root.ts";
import { registerDaemonReporter } from "./reporter.ts";
import {
	type DaemonToolDeps,
	registerAskAgentTool,
	registerCancelAgentTool,
	registerDaemonTools,
	registerPeerMessageTools,
} from "./tools.ts";
import { resolveAgentDepthState } from "./types.ts";
import { type ActiveAgentsWidgetController, startActiveAgentsWidget } from "./widget.ts";

// The agent plugin's session surfaces: dispatch/ask/cancel/peer tools, the run
// reporter, and the connect-time wiring (peer-message delivery + active-agents
// widget). The hub connection itself is core-owned (#core/hub); this rides on it.

function defaultAgentToolDeps(): DaemonToolDeps {
	return {
		hasInvokedSkill,
		getWorkspaceState,
		basecampExtensionRoot: basecampExtensionRoot(),
		resolveModelAlias,
	};
}

export function registerAgentSurfaces(pi: ExtensionAPI, deps: DaemonToolDeps = defaultAgentToolDeps()): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();
	const runId = process.env.BASECAMP_RUN_ID;
	const isDaemonSpawnedAgent = !isTopLevel && Boolean(runId);

	if (!isTopLevel && !isDaemonSpawnedAgent) {
		return;
	}

	if (isTopLevel && !atMaxDepth) {
		registerDaemonTools(pi, awaitDaemonConnection, deps);
	}

	if (isDaemonSpawnedAgent && !atMaxDepth) {
		registerAskAgentTool(pi, awaitDaemonConnection, deps);
		registerPeerMessageTools(pi, awaitDaemonConnection, { hasInvokedSkill: deps.hasInvokedSkill });
		registerCancelAgentTool(pi, awaitDaemonConnection, { hasInvokedSkill: deps.hasInvokedSkill });
	}

	if (isDaemonSpawnedAgent && runId && process.env.BASECAMP_AGENT_ID) {
		registerDaemonReporter(pi, {
			awaitConnection: awaitDaemonConnection,
			runId,
			agentId: process.env.BASECAMP_AGENT_ID,
		});
	}

	// Re-wire the delivery handler + widget whenever the hub connection is (re)established.
	const peerState: PeerDeliveryState = { peerDeliveryConnection: null, peerDeliveryUnsubscribe: null };
	onDaemonConnect((connection, ctx) => {
		registerPeerMessageDeliveryHandler(pi, peerState, connection);
		let widget: ActiveAgentsWidgetController | null = null;
		if (isTopLevel && ctx.hasUI) {
			widget = startActiveAgentsWidget(ctx, {
				rootId: deriveDaemonIdentity(ctx).node_id,
				socketPath: process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
				fetchSummary: fetchRunSummary,
			});
		}
		return () => {
			peerState.peerDeliveryUnsubscribe?.();
			peerState.peerDeliveryUnsubscribe = null;
			peerState.peerDeliveryConnection = null;
			widget?.stop();
		};
	});
}
