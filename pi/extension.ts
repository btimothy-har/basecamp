/**
 * Basecamp composition root — the only wiring manifest in the repo.
 *
 * Modules register in a fixed order (core first), so in-extension init is
 * deterministic and identical on /reload. A module that throws during
 * registration is degraded (logged and skipped) rather than taking the whole
 * extension down; import-time errors are still shared fate by design.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import registerBashReviewer from "#bash-reviewer/index.ts";
import registerBrowser from "#browser/index.ts";
import registerCodeReview from "#code-review/index.ts";
import registerCore from "#core/index.ts";
import registerEngineering from "#engineering/index.ts";
import registerPullRequest from "#pull-request/index.ts";
import registerSystemPrompt from "#system-prompt/index.ts";
import registerTasks from "#tasks/index.ts";
import registerWorkstreams from "#workstreams/index.ts";

const MODULES: ReadonlyArray<readonly [string, (pi: ExtensionAPI) => void]> = [
	["core", registerCore],
	["system-prompt", registerSystemPrompt],
	["tasks", registerTasks],
	["bash-reviewer", registerBashReviewer],
	["engineering", registerEngineering],
	["pull-request", registerPullRequest],
	["browser", registerBrowser],
	["code-review", registerCodeReview],
	["workstreams", registerWorkstreams],
];

export default function (pi: ExtensionAPI): void {
	for (const [name, register] of MODULES) {
		try {
			register(pi);
		} catch (error) {
			console.error(`[basecamp] module "${name}" failed to register:`, error);
		}
	}
}
