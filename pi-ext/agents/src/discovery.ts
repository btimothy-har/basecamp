/**
 * Re-export agent discovery from the shared module.
 *
 * Discovery lives in pi-ext/discovery.ts so both agents/src (tool
 * registration) and core/src (prompt assembly) can import it without
 * cross-module imports.
 */

export { discoverAgents } from "../../discovery.ts";
