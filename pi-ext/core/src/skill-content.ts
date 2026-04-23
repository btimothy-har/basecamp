/**
 * Shared helpers for loading and rendering skill file content.
 *
 * Covers the common pipeline: read file → strip frontmatter → wrap in XML.
 * Resolution (finding file paths from names) stays with each caller.
 */

import { readFileSync } from "node:fs";
import { stripFrontmatter } from "@mariozechner/pi-coding-agent";
import { escapeXml } from "../../utils";

/**
 * Read a skill file and return its content with frontmatter stripped.
 * Returns null if the file cannot be read or is empty after stripping.
 */
export function readSkillContent(filePath: string): string | null {
	let raw: string;
	try {
		raw = readFileSync(filePath, "utf-8");
	} catch {
		return null;
	}
	const content = stripFrontmatter(raw).trim();
	return content.length > 0 ? content : null;
}

/**
 * Wrap skill content in a `<skill name="...">...</skill>` XML block.
 */
export function buildSkillBlock(name: string, content: string): string {
	return `<skill name="${escapeXml(name)}">\n${content}\n</skill>`;
}

/**
 * Convenience: read + strip + wrap in one call.
 * Returns null if the file cannot be read or yields no content.
 */
export function loadSkillBlock(name: string, filePath: string): string | null {
	const content = readSkillContent(filePath);
	if (content === null) return null;
	return buildSkillBlock(name, content);
}
