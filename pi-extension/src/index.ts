import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import registerCapabilities from "../capabilities/src/index.ts";
import registerEngineering from "../engineering/src/index.ts";
import registerGit from "../git/src/index.ts";
import registerModelAliases from "../model-aliases/src/index.ts";
import registerProjects from "../projects/src/index.ts";
import registerSession from "../session/src/index.ts";
import registerState from "../state/src/index.ts";
import registerWorkflow from "../workflow/src/index.ts";
import registerWorkspace from "../workspace/src/index.ts";

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
