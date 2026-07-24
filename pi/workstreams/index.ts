import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { awaitDaemonConnection } from "#core/hub/index.ts";
import { resolveAgentDepthState } from "#core/swarm/agents/types.ts";
import { registerWorkstreamStartup } from "./start.ts";
import { registerWorkstreamTools } from "./tools.ts";

const workstreamsDir = path.dirname(fileURLToPath(import.meta.url));
export const workstreamsSkillPath = path.join(workstreamsDir, "skills", "workstreams", "SKILL.md");

/**
 * The workstreams feature domain — durable, repo-neutral coordination state for
 * copilot-staged work, built on the swarm primitive (`#core/swarm`). Tools are
 * top-level only; the `pi --workstream` startup attaches the session as an
 * additive workstream agent.
 */
export default function registerWorkstreams(pi: ExtensionAPI): void {
	const { isTopLevel, atMaxDepth } = resolveAgentDepthState();

	if (isTopLevel && !atMaxDepth) {
		registerWorkstreamTools(pi, awaitDaemonConnection);
		pi.on("resources_discover", () => ({ skillPaths: [workstreamsSkillPath] }));
	}
	if (isTopLevel) {
		registerWorkstreamStartup(pi, awaitDaemonConnection);
	}
}
