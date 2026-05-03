/**
 * Shared helpers for git commands.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { exec } from "../../platform/exec";
import { loadTemplate as _loadTemplate } from "../../platform/templates";
import { getWorkspaceState } from "../../platform/workspace";

const RESOURCES = path.resolve(__dirname, "..", "resources");
const PRIVATE_DIR_MODE = 0o700;

export function loadTemplate(name: string, vars: Record<string, string>): string {
	return _loadTemplate(RESOURCES, name, vars);
}

export function getScratchDir(cwd: string): string {
	return getWorkspaceState()?.scratchDir ?? `/tmp/pi/${path.basename(cwd)}`;
}

function isNotFoundError(error: unknown): boolean {
	return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}

function ensurePrivateDirectory(dir: string): void {
	try {
		const stat = fs.lstatSync(dir);
		if (stat.isSymbolicLink()) throw new Error(`Unsafe scratch directory: ${dir} is a symlink`);
		if (!stat.isDirectory()) throw new Error(`Unsafe scratch directory: ${dir} is not a directory`);
	} catch (error) {
		if (!isNotFoundError(error)) throw error;
		fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE });
	}

	const stat = fs.lstatSync(dir);
	if (stat.isSymbolicLink()) throw new Error(`Unsafe scratch directory: ${dir} is a symlink`);
	if (!stat.isDirectory()) throw new Error(`Unsafe scratch directory: ${dir} is not a directory`);
	fs.chmodSync(dir, PRIVATE_DIR_MODE);
}

export function getIssueDraftDir(cwd: string): string {
	const issueDir = path.join(getScratchDir(cwd), "issues");
	ensurePrivateDirectory(issueDir);
	return issueDir;
}

export function createIssueDraftPath(cwd: string): string {
	const issueDir = getIssueDraftDir(cwd);

	for (let attempt = 0; attempt < 10; attempt += 1) {
		const filename = `draft-${Date.now()}-${crypto.randomBytes(8).toString("hex")}.md`;
		const draftPath = path.join(issueDir, filename);
		if (!fs.existsSync(draftPath)) return draftPath;
	}

	throw new Error("Unable to allocate a unique issue draft path");
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
