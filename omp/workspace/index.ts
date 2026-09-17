/** Workspace lifecycle registration for bare and Basecamp-launched OMP. */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { readWorkspaceEnvironment } from "./environment.ts";
import registerWorkspaceGuard from "./guard.ts";
import registerWorkspaceGuidance from "./guidance.ts";
import { RepositoryCache } from "./repository.ts";
import registerStartupWarning from "./startup.ts";

export default function registerWorkspace(pi: ExtensionAPI): void {
	const repos = new RepositoryCache();
	const env = readWorkspaceEnvironment();
	registerStartupWarning(pi, repos);
	registerWorkspaceGuard(pi, { env, repos });
	registerWorkspaceGuidance(pi, { env, repos });
}
