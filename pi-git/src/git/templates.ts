/**
 * Shared template loading — read .md files from a resources directory
 * with optional {{var}} substitution.
 */

import fs from "node:fs";
import path from "node:path";

export function loadTemplate(baseDir: string, name: string, vars?: Record<string, string>): string {
	let content = fs.readFileSync(path.join(baseDir, `${name}.md`), "utf-8").trim();
	if (vars) {
		for (const [key, value] of Object.entries(vars)) {
			content = content.replaceAll(`{{${key}}}`, value);
		}
	}
	return content;
}
