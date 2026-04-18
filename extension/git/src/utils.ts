/**
 * Shared helpers for git commands.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const RESOURCES = path.resolve(__dirname, "..", "resources");

export function loadTemplate(name: string, vars: Record<string, string>): string {
	let template = fs.readFileSync(path.join(RESOURCES, `${name}.md`), "utf8");
	for (const [key, value] of Object.entries(vars)) {
		template = template.replaceAll(`{{${key}}}`, value);
	}
	return template;
}

export function getScratchDir(cwd: string): string {
	return process.env.BASECAMP_SCRATCH_DIR || `/tmp/pi/${path.basename(cwd)}`;
}

export async function resolvePrNumber(
	pi: ExtensionAPI,
	prArg: string | undefined,
	ctx: any,
): Promise<{ number: string; branch: string } | null> {
	if (prArg) {
		const result = await pi.exec("gh", ["pr", "view", prArg, "--json", "headRefName", "-q", ".headRefName"]);
		if (result.code !== 0) {
			ctx.ui.notify(`PR #${prArg} not found`, "error");
			return null;
		}
		return { number: prArg, branch: result.stdout.trim() };
	}

	const branch = await pi.exec("git", ["branch", "--show-current"]);
	const branchName = branch.stdout.trim();
	if (!branchName) {
		ctx.ui.notify("Not on a branch", "error");
		return null;
	}

	const existing = await pi.exec("gh", ["pr", "list", "--head", branchName, "--json", "number", "-q", ".[0].number"]);
	if (!existing.stdout.trim()) {
		ctx.ui.notify(`No PR found for branch ${branchName}`, "error");
		return null;
	}
	return { number: existing.stdout.trim(), branch: branchName };
}
