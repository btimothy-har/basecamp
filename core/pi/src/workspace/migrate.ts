import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "./constants.ts";
import { gitOutput } from "./repo.ts";
import {
	labelFromWorktreePath,
	parseWorktreeList,
	validateNoSymlinkedWorktreePath,
	validateWorktreePath,
} from "./worktree.ts";

export interface PlannedWorktreeMove {
	src: string;
	dest: string;
	label: string;
}

export interface LegacyMigrationPlan {
	moves: PlannedWorktreeMove[];
}

export interface LegacyMigrationResult {
	moved: string[];
	skipped: { label: string; reason: string }[];
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return !!relative && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function isPathEqualOrWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

export function planLegacyWorktreeMigration(opts: {
	records: { path: string; branch: string | null }[];
	identity: string;
	cwd: string;
}): LegacyMigrationPlan {
	if (!opts.identity.includes("/")) return { moves: [] };
	if (opts.records.length === 0) return { moves: [] };

	const mainRecord = opts.records[0];
	if (!mainRecord) return { moves: [] };

	const mainPath = path.resolve(mainRecord.path);
	const bareName = path.basename(mainPath);
	const legacyRoot = path.join(WORKTREES_ROOT, bareName);
	const newRoot = path.join(WORKTREES_ROOT, opts.identity);
	if (legacyRoot === newRoot) return { moves: [] };

	const cwd = path.resolve(opts.cwd);
	const moves: PlannedWorktreeMove[] = [];
	for (const record of opts.records.slice(1)) {
		const p = path.resolve(record.path);
		if (!isPathWithin(p, legacyRoot)) continue;
		if (isPathEqualOrWithin(p, newRoot)) continue;
		if (p === cwd || isPathEqualOrWithin(cwd, p)) continue;

		try {
			const label = labelFromWorktreePath(bareName, p);
			moves.push({ src: p, dest: path.join(newRoot, label), label });
		} catch {}
	}

	return { moves };
}

export function shouldRetryMoveWithForce(stderr: string): boolean {
	const normalized = stderr.toLowerCase();
	if (normalized.includes("locked")) return false;
	return (
		normalized.includes("use --force") ||
		normalized.includes("modified or untracked") ||
		normalized.includes("contains modified")
	);
}

function shortReason(value: unknown): string {
	const message = value instanceof Error ? value.message : String(value);
	const [firstLine] = message.trim().split("\n");
	return firstLine || "unknown error";
}

export async function migrateLegacyWorktrees(
	pi: ExtensionAPI,
	opts: { repoRoot: string; identity: string; cwd: string },
): Promise<LegacyMigrationResult> {
	const result: LegacyMigrationResult = { moved: [], skipped: [] };
	if (!opts.identity.includes("/")) return result;

	let output: string;
	try {
		output = await gitOutput(pi, opts.repoRoot, ["worktree", "list", "--porcelain"]);
	} catch {
		return result;
	}

	const records = parseWorktreeList(output);
	const mainRecord = records[0];
	if (!mainRecord) return result;

	const bareName = path.basename(path.resolve(mainRecord.path));
	if (!fs.existsSync(path.join(WORKTREES_ROOT, bareName))) return result;

	const plan = planLegacyWorktreeMigration({ records, identity: opts.identity, cwd: opts.cwd });
	for (const move of plan.moves) {
		try {
			if (fs.existsSync(move.dest)) {
				result.skipped.push({ label: move.label, reason: "destination exists" });
				continue;
			}

			try {
				validateWorktreePath(opts.identity, move.label, move.dest);
				validateNoSymlinkedWorktreePath(move.dest);
			} catch (error) {
				result.skipped.push({ label: move.label, reason: shortReason(error) });
				continue;
			}

			fs.mkdirSync(path.dirname(move.dest), { recursive: true });
			let moveResult = await pi.exec("git", ["-C", opts.repoRoot, "worktree", "move", move.src, move.dest], {
				timeout: 30_000,
			});
			if (moveResult.code !== 0 && shouldRetryMoveWithForce(moveResult.stderr)) {
				moveResult = await pi.exec("git", ["-C", opts.repoRoot, "worktree", "move", "--force", move.src, move.dest], {
					timeout: 30_000,
				});
			}
			if (moveResult.code !== 0) {
				result.skipped.push({ label: move.label, reason: shortReason(moveResult.stderr) });
				continue;
			}

			result.moved.push(move.label);
		} catch (error) {
			result.skipped.push({ label: move.label, reason: shortReason(error) });
		}
	}

	return result;
}
