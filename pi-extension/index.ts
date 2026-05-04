import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import registerCapabilities from "./src/capabilities/index.ts";
import registerEngineering from "./src/engineering/index.ts";
import registerGit from "./src/git/index.ts";
import registerModelAliases from "./src/model-aliases/index.ts";
import registerProjects from "./src/projects/index.ts";
import registerSession from "./src/session/index.ts";
import registerState from "./src/state/index.ts";
import registerWorkflow from "./src/workflow/index.ts";
import registerWorkspace from "./src/workspace/index.ts";

export default function (pi: ExtensionAPI): void {
	registerState(pi);
	registerWorkspace(pi);
	registerModelAliases(pi);
	registerSession(pi);
	registerCapabilities(pi);
	registerEngineering(pi);
	registerProjects(pi);
	registerWorkflow(pi);
	registerGit(pi);
}
