/**
 * Shared helpers for git commands.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { exec } from "../../core/src/runtime/session";
import { loadTemplate as _loadTemplate } from "../../platform/templates";

const RESOURCES = path.resolve(__dirname, "..", "resources");

export function loadTemplate(name: string, vars: Record<string, string>): string {
	return _loadTemplate(RESOURCES, name, vars);
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
		const result = await exec(pi, "gh", ["pr", "view", prArg, "--json", "headRefName", "-q", ".headRefName"]);
		if (result.code !== 0) {
			ctx.ui.notify(`PR #${prArg} not found`, "error");
			return null;
		}
		return { number: prArg, branch: result.stdout.trim() };
	}

	const branch = await exec(pi, "git", ["branch", "--show-current"]);
	const branchName = branch.stdout.trim();
	if (!branchName) {
		ctx.ui.notify("Not on a branch", "error");
		return null;
	}

	const existing = await exec(pi, "gh", ["pr", "list", "--head", branchName, "--json", "number", "-q", ".[0].number"]);
	if (!existing.stdout.trim()) {
		ctx.ui.notify(`No PR found for branch ${branchName}`, "error");
		return null;
	}
	return { number: existing.stdout.trim(), branch: branchName };
}
