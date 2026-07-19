import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";

const browserDir = path.dirname(fileURLToPath(import.meta.url));
export const browserCliBinDir = path.join(browserDir, "bin");
export const browserSkillPath = path.join(browserDir, "skills", "playwright-cli", "SKILL.md");

export function browserCliPath(currentPath: string | undefined, enabled: boolean): string | undefined {
	const entries = currentPath?.split(path.delimiter) ?? [];
	const withoutBrowserCli = entries.filter((entry) => entry !== browserCliBinDir);
	if (enabled) return [browserCliBinDir, ...withoutBrowserCli].join(path.delimiter);
	return currentPath === undefined ? undefined : withoutBrowserCli.join(path.delimiter);
}

export function configureBrowserCliPath(enabled: boolean): void {
	const nextPath = browserCliPath(process.env.PATH, enabled);
	if (nextPath === undefined) delete process.env.PATH;
	else process.env.PATH = nextPath;
}

export default function (pi: ExtensionAPI): void {
	const enabled = !isSubagent();
	configureBrowserCliPath(enabled);
	if (!enabled) return;

	pi.on("resources_discover", () => ({ skillPaths: [browserSkillPath] }));
}
