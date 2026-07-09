/**
 * Project context-file loader.
 *
 * Discovers and reads the pi-native context files (AGENTS.md / CLAUDE.md) that
 * describe a project. The prompt-fragment builders that consume these live in
 * the workspace domain (workspace/prompt/context-builders.ts).
 */

import * as fs from "node:fs";
import * as path from "node:path";

export interface ContextFile {
	path: string;
	content: string;
}

const CONTEXT_FILE_NAMES = ["AGENTS.md", "CLAUDE.md"];

export function loadContextFileFromDir(dir: string): ContextFile | null {
	for (const filename of CONTEXT_FILE_NAMES) {
		const filePath = path.join(dir, filename);
		try {
			const content = fs.readFileSync(filePath, "utf-8");
			return { path: filePath, content };
		} catch {
			// Not found, try next candidate
		}
	}
	return null;
}

/**
 * Discover AGENTS.md / CLAUDE.md files by walking up from cwd.
 *
 * Matches pi's native discovery: checks each directory from cwd
 * to filesystem root, returns files in root-first order.
 * Deduplicates by path.
 */
export function discoverContextFiles(cwd: string): ContextFile[] {
	const files: ContextFile[] = [];
	const seen = new Set<string>();

	let dir = cwd;
	while (true) {
		const file = loadContextFileFromDir(dir);
		if (file && !seen.has(file.path)) {
			files.unshift(file);
			seen.add(file.path);
		}
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}

	return files;
}
