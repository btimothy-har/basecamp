import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { PiSwarmDependencies } from "../../../pi-swarm/extension/src/dependencies.ts";
import { buildSkillBlock, readSkillContent } from "../capabilities/skill-content.ts";
import { registerCatalogProvider } from "../platform/catalog.ts";
import { setDaemonStatus } from "../platform/daemon-status.ts";
import { resolveModelAlias } from "../platform/model-aliases.ts";
import { hasInvokedSkill } from "../platform/skill-tracker.ts";
import { getWorkspaceState } from "../platform/workspace.ts";
import { formatTitle, shortSessionId } from "../session/ui/title.ts";
import { formatTaskProgressSummary, renderCompactTaskProgressLines } from "./tasks/render.ts";

function basecampExtensionRootFromAdapter(): string {
	const here = path.dirname(fileURLToPath(import.meta.url));
	return path.resolve(here, "..", "..");
}

export function createPiSwarmDependencies(): PiSwarmDependencies {
	return {
		basecampExtensionRoot: basecampExtensionRootFromAdapter(),
		registerCatalogProvider,
		resolveModelAlias,
		hasInvokedSkill,
		getWorkspaceState,
		readSkillContent,
		buildSkillBlock,
		formatTaskProgressSummary,
		renderCompactTaskProgressLines,
		setDaemonStatus,
		formatTitle,
		shortSessionId,
	};
}
