/**
 * File-length check — enforces the hard caps from AGENTS.md
 * (Development → File Length Limits):
 *
 *   TypeScript (.ts) ≤ 350 lines · Python (.py) ≤ 500 lines
 *
 * The cap is a module-design forcing function: a file that outgrows it gets
 * split along responsibility seams, never compressed to sneak under. Files
 * that predate the rule are pinned in GRANDFATHERED at their then-current
 * size and may only shrink; once one drops to or under its cap, its entry
 * must be removed. Never add an entry.
 *
 * Run: node scripts/check-file-length.ts (wired into npm run check / lint).
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(import.meta.dirname, "..");

const LIMITS: Readonly<Record<string, number>> = {
	".ts": 350,
	".py": 500,
};

const SKIP_DIRS = new Set([".git", ".claude", ".venv", ".pytest_cache", "__pycache__", "dist", "node_modules"]);

/**
 * Shrink-only ratchet: files that predate the rule, pinned at their size when
 * it landed. Entries may never be added or raised — only removed (mandatory
 * once the file is back under its cap).
 */
const GRANDFATHERED: Readonly<Record<string, number>> = {
	"bash-reviewer/ts/reviewer/triage.ts": 794,
	"bash-reviewer/ts/tests/review.test.ts": 481,
	"companion/py/basecamp/companion/app.py": 515,
	"companion/py/basecamp/companion/daemon.py": 614,
	"companion/py/tests/test_companion_app.py": 678,
	"companion/py/tests/test_companion_dashboard.py": 577,
	"companion/py/tests/test_companion_swarm.py": 533,
	"companion/ts/tests/panes-index.test.ts": 509,
	"core/ts/escalate/dialog.ts": 486,
	"core/ts/model-aliases/commands.ts": 364,
	"core/ts/state/index.ts": 371,
	"core/ts/state/tests/session-state.test.ts": 425,
	"engineering/ts/tools/bq-query.ts": 1284,
	"swarm/py/basecamp/swarm/service.py": 1094,
	"swarm/py/basecamp/swarm/store.py": 1829,
	"swarm/py/tests/test_daemon_app.py": 1691,
	"swarm/py/tests/test_daemon_dispatch.py": 3066,
	"swarm/py/tests/test_daemon_store.py": 2670,
	"swarm/py/tests/test_runner.py": 574,
	"swarm/ts/workstreams/tests/start.test.ts": 484,
	"swarm/ts/workstreams/tests/tools.test.ts": 649,
	"swarm/ts/workstreams/tools.ts": 953,
	"tasks/ts/planning/plan.ts": 756,
	"tasks/ts/planning/review.ts": 557,
	"tasks/ts/tasks/tasks.ts": 698,
	"ui/ts/tests/title-state.test.ts": 359,
	"ui/ts/title.ts": 450,
	"workspace/ts/workspace/tests/service.test.ts": 511,
};

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
const unseen = new Set(Object.keys(GRANDFATHERED));
let checked = 0;

for (const file of walk(REPO_ROOT).sort()) {
	const rel = path.relative(REPO_ROOT, file);
	const limit = LIMITS[path.extname(file)];
	if (limit === undefined) continue;
	checked += 1;
	const lines = lineCount(file);
	const pinned = GRANDFATHERED[rel];
	if (pinned !== undefined) {
		unseen.delete(rel);
		if (lines <= limit) {
			violations.push(`${rel}: ${lines} lines is within the ${limit}-line cap — remove its GRANDFATHERED entry`);
		} else if (lines > pinned) {
			violations.push(
				`${rel}: grew ${pinned} → ${lines} lines — grandfathered files may only shrink (split along responsibility seams; cap ${limit})`,
			);
		}
		continue;
	}
	if (lines > limit) {
		violations.push(
			`${rel}: ${lines} lines exceeds the ${limit}-line cap — split along responsibility seams (AGENTS.md → File Length Limits)`,
		);
	}
}

for (const rel of [...unseen].sort()) {
	violations.push(`GRANDFATHERED entry "${rel}" matches no file — remove it`);
}

if (violations.length > 0) {
	console.error(`File-length check failed (${violations.length} violation${violations.length === 1 ? "" : "s"}):\n`);
	for (const violation of violations) console.error(`  ${violation}`);
	process.exit(1);
}

console.log(`File-length check passed (${checked} files).`);
