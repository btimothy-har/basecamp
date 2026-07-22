/**
 * File-length check — enforces the hard caps from AGENTS.md
 * (Development → File Length Limits):
 *
 *   TypeScript (.ts) ≤ 350 lines · Python/HTML/CSS/JavaScript ≤ 500 lines
 *
 * The cap is a module-design forcing function: a file that outgrows it gets
 * split along responsibility seams, never compressed to sneak under. There
 * are no per-file exceptions; the shrink-only GRANDFATHERED ratchet that
 * migrated pre-rule files reached zero and was removed (see git history).
 *
 * Run: node scripts/check-file-length.ts (wired into npm run check / lint).
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(import.meta.dirname, "..");

const LIMITS: Readonly<Record<string, number>> = {
	".ts": 350,
	".py": 500,
	".html": 500,
	".css": 500,
	".js": 500,
};

const SKIP_DIRS = new Set([".git", ".claude", ".venv", ".pytest_cache", "__pycache__", "dist", "node_modules"]);

function walk(dir: string, out: string[] = []): string[] {
	for (const entry of readdirSync(dir)) {
		const full = path.join(dir, entry);
		if (statSync(full).isDirectory()) {
			if (!SKIP_DIRS.has(entry)) walk(full, out);
		} else if (path.extname(entry) in LIMITS) {
			out.push(full);
		}
	}
	return out;
}

function lineCount(file: string): number {
	const content = readFileSync(file, "utf8");
	if (content === "") return 0;
	const segments = content.split("\n").length;
	return content.endsWith("\n") ? segments - 1 : segments;
}

const violations: string[] = [];
let checked = 0;

for (const file of walk(REPO_ROOT).sort()) {
	const rel = path.relative(REPO_ROOT, file);
	const limit = LIMITS[path.extname(file)];
	if (limit === undefined) continue;
	checked += 1;
	const lines = lineCount(file);
	if (lines > limit) {
		violations.push(
			`${rel}: ${lines} lines exceeds the ${limit}-line cap — split along responsibility seams (AGENTS.md → File Length Limits)`,
		);
	}
}

if (violations.length > 0) {
	console.error(`File-length check failed (${violations.length} violation${violations.length === 1 ? "" : "s"}):\n`);
	for (const violation of violations) console.error(`  ${violation}`);
	process.exit(1);
}

console.log(`File-length check passed (${checked} files).`);
