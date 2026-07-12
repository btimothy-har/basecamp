import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { processScoped } from "#core/global-registry.ts";
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

/**
 * Connect-time wiring that must survive /reload. The hub WebSocket outlives a
 * reload (core's processScoped connection), so on reload `onDaemonConnect` re-fires
 * on the SAME connection. Keeping the delivery-handler unsubscribe + widget handle
 * in surviving state lets us tear down the prior wiring before re-wiring — otherwise
 * a reload double-subscribes the peer_message_delivery handler (duplicate delivery +
 * acks) and leaks the widget's refresh interval.
 */
interface AgentConnectState extends PeerDeliveryState {
	widget: ActiveAgentsWidgetController | null;
}

const getAgentConnectState = processScoped<AgentConnectState>("basecamp.swarm.agentConnect", () => ({
	peerDeliveryConnection: null,
	peerDeliveryUnsubscribe: null,
	widget: null,
}));

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
	onDaemonConnect((connection, ctx) => {
		const connectState = getAgentConnectState();
		// A surviving connection can outlive /reload, so tear down any prior wiring
		// before re-wiring: registerPeerMessageDeliveryHandler unsubscribes the previous
		// handler via connectState.peerDeliveryUnsubscribe (keeping exactly one), and we
		// stop the previous widget so its refresh interval doesn't leak.
		connectState.widget?.stop();
		connectState.widget = null;
		registerPeerMessageDeliveryHandler(pi, connectState, connection);
		if (isTopLevel && ctx.hasUI) {
			connectState.widget = startActiveAgentsWidget(ctx, {
				rootId: deriveDaemonIdentity(ctx).node_id,
				socketPath: process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
				fetchSummary: fetchRunSummary,
			});
		}
		return () => {
			connectState.peerDeliveryUnsubscribe?.();
			connectState.peerDeliveryUnsubscribe = null;
			connectState.peerDeliveryConnection = null;
			connectState.widget?.stop();
			connectState.widget = null;
		};
	});
}
