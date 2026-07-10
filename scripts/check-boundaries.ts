/**
 * Import-boundary check — enforces the modularity contract from
 * docs/design/repo-consolidation.md §5:
 *
 *   1. A context may import #core/* freely.
 *   2. A context may import another context only via its public entry
 *      (#<context>/index.ts). Same-context imports must be relative.
 *   3. Relative imports may not escape the context's pi/<context> directory.
 *   4. core imports no other context.
 *   5. Legacy package specifiers (pi-core/…, pi-ui/…, pi-tasks/…) are gone.
 *
 * Run: node scripts/check-boundaries.ts (wired into npm run check / lint).
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(import.meta.dirname, "..");

const CONTEXTS = [
	"core",
	"system-prompt",
	"tasks",
	"git",
	"bash-reviewer",
	"engineering",
	"browser",
	"companion",
	"swarm",
] as const;

const LEGACY_SPECIFIERS = ["pi-core", "pi-ui", "pi-tasks", "pi-workspace", "pi-git", "pi-bash-reviewer"];

/**
 * Deep-import exceptions. Empty since the phase-2 seam collapse — kept so a
 * deliberate, documented exception has somewhere to live if one is ever needed.
 */
const DEEP_IMPORT_ALLOWLIST: Record<string, readonly string[]> = {};

function walk(dir: string, out: string[] = []): string[] {
	for (const entry of readdirSync(dir)) {
		const full = path.join(dir, entry);
		if (statSync(full).isDirectory()) {
			if (entry === "node_modules") continue;
			walk(full, out);
		} else if (entry.endsWith(".ts")) {
			out.push(full);
		}
	}
	return out;
}

/** Extract import/export specifiers, including dynamic import("..."). */
function specifiersOf(source: string): string[] {
	const specifiers: string[] = [];
	const pattern = /(?:from\s*|import\s*\(\s*|^\s*import\s+)["']([^"']+)["']/gm;
	for (const match of source.matchAll(pattern)) {
		const spec = match[1];
		if (spec) specifiers.push(spec);
	}
	return specifiers;
}

const violations: string[] = [];

for (const context of CONTEXTS) {
	const tsRoot = path.join(REPO_ROOT, "pi", context);
	let files: string[];
	try {
		files = walk(tsRoot);
	} catch {
		violations.push(`${context}: missing pi/${context} directory at ${tsRoot}`);
		continue;
	}

	const allowlist = DEEP_IMPORT_ALLOWLIST[context] ?? [];

	for (const file of files) {
		const relFile = path.relative(REPO_ROOT, file);
		for (const spec of specifiersOf(readFileSync(file, "utf8"))) {
			if (LEGACY_SPECIFIERS.some((legacy) => spec === legacy || spec.startsWith(`${legacy}/`))) {
				violations.push(`${relFile}: legacy package specifier "${spec}"`);
				continue;
			}
			if (spec.startsWith("#") || spec.startsWith(".")) {
				// Pi's loader tolerates extensionless imports; strict Node (our test
				// runner) does not. Enforce the explicit-.ts convention everywhere.
				if (!spec.endsWith(".ts")) {
					violations.push(`${relFile}: import "${spec}" must use an explicit .ts extension`);
				}
			}
			if (spec.startsWith("#")) {
				const [alias] = spec.slice(1).split("/", 1);
				const target = alias ?? "";
				if (!CONTEXTS.includes(target as (typeof CONTEXTS)[number])) {
					violations.push(`${relFile}: unknown context alias "${spec}"`);
				} else if (target === context) {
					violations.push(`${relFile}: same-context import "${spec}" must be relative`);
				} else if (target === "core") {
					// rule 1: #core/* is free — but core itself may not import contexts (rule 4)
				} else if (spec !== `#${target}/index.ts` && !allowlist.includes(spec)) {
					violations.push(`${relFile}: deep cross-context import "${spec}" (use #${target}/index.ts)`);
				}
				if (context === "core") {
					violations.push(`${relFile}: core must not import other contexts ("${spec}")`);
				}
				continue;
			}
			if (spec.startsWith(".")) {
				const resolved = path.resolve(path.dirname(file), spec);
				if (!resolved.startsWith(tsRoot + path.sep) && resolved !== tsRoot) {
					violations.push(`${relFile}: relative import escapes context ts/ ("${spec}")`);
				}
			}
			// bare specifiers (node:, @earendil-works/*, ws, …) are fine
		}
	}
}

if (violations.length > 0) {
	console.error(`Boundary check failed (${violations.length} violation${violations.length === 1 ? "" : "s"}):\n`);
	for (const violation of violations) console.error(`  ${violation}`);
	process.exit(1);
}

console.log(`Boundary check passed (${CONTEXTS.length} contexts).`);
