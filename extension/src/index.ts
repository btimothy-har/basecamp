import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerLifecycle } from "./lifecycle";
import { registerGitProtect } from "./git-protect";
import { registerObserver } from "./observer";
import { registerNudges } from "./nudges";
import { registerHandoff } from "./handoff";
import { discoverAgents } from "./agents/discovery";
import { registerWorkerTool } from "./agents/tool";
import { registerAgentCommands } from "./agents/commands";
import { closeWorker } from "./agents/worker-index";
import type { AgentConfig } from "./agents/types";

export default function (pi: ExtensionAPI) {
  let agents: AgentConfig[] = [];
  let sessionName = "";

  registerLifecycle(pi);
  registerGitProtect(pi);
  registerObserver(pi);
  registerNudges(pi);
  registerHandoff(pi);

  // --- Agent discovery and session naming ---

  pi.on("session_start", async (_event, ctx) => {
    agents = discoverAgents(ctx.cwd);

    // Ensure this session has a stable name for worker targeting
    sessionName = pi.getSessionName()?.trim() || "";
    if (!sessionName) {
      const project = process.env.BASECAMP_PROJECT || "session";
      const id = ctx.sessionManager.getSessionId().slice(0, 8);
      sessionName = `bc-${project}-${id}`;
      pi.setSessionName(sessionName);
    }
    process.env.BASECAMP_SESSION_NAME = sessionName;

    if (agents.length > 0) {
      ctx.ui.notify(
        `basecamp: ${agents.length} agent(s) discovered`,
        "info",
      );
    }
  });

  // --- Register worker tool and slash commands ---

  registerWorkerTool(
    pi,
    () => agents,
    () => sessionName,
  );
  registerAgentCommands(pi, () => agents);

  // --- Worker cleanup on session shutdown ---

  pi.on("session_shutdown", async () => {
    const workerName = process.env.BASECAMP_WORKER_NAME;
    if (workerName) closeWorker(workerName);
  });
}
