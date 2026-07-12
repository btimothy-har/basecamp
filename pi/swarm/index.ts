import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { awaitDaemonConnection } from "#core/hub/index.ts";
import { registerAgentSurfaces } from "./agents/daemon/index.ts";
import { registerAgentCatalog } from "./agents/index.ts";
import { registerReviewCommand } from "./agents/review/command.ts";
import { resolveAgentDepthState } from "./agents/types.ts";
import { registerWorkstreamStartup } from "./workstreams/start.ts";
import { registerWorkstreamTools } from "./workstreams/tools.ts";

export { reportThread, type ThreadReport } from "./agents/daemon/report-thread.ts";

function registerWorkstreams(pi: ExtensionAPI): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();

	if (isTopLevel && !atMaxDepth) {
		registerWorkstreamTools(pi, awaitDaemonConnection);
	}
	if (isTopLevel) {
		registerWorkstreamStartup(pi, awaitDaemonConnection);
	}
}

export default function (pi: ExtensionAPI): void {
	registerAgentCatalog();
	registerAgentSurfaces(pi);
	registerReviewCommand(pi);
	registerWorkstreams(pi);
}
