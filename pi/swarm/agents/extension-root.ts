import * as path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The basecamp extension package root — the repo root, since the whole repo
 * is the (single) Pi package. Used to recognize tools sourced from basecamp
 * itself when building subagent tool allowlists.
 */
export function basecampExtensionRoot(): string {
	// pi/swarm/agents/ -> repo root
	return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
}
