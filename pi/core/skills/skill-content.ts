/**
 * Shared helpers for loading and rendering skill file content.
 *
 * Covers the common pipeline: read file → strip frontmatter → wrap in XML.
 * Resolution (finding file paths from names) stays with each caller.
 */

import { readFileSync } from "node:fs";
import { parseFrontmatter, stripFrontmatter } from "@earendil-works/pi-coding-agent";

function escapeXml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&apos;");
}

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

/**
 * True when a skill file's frontmatter sets `disable-model-invocation: true`.
 * Such skills are user-invoked only (via `/skill:name`): Basecamp hides them
 * from the model's capability index and the `skill` tool refuses to load them.
 * Pi's own `disableModelInvocation` filter applies only to its default prompt,
 * which Basecamp replaces — so Basecamp must enforce the flag itself.
 */
export function isModelInvocationDisabled(filePath: string): boolean {
	let raw: string;
	try {
		raw = readFileSync(filePath, "utf-8");
	} catch {
		return false;
	}
	const { frontmatter } = parseFrontmatter<{ "disable-model-invocation"?: boolean }>(raw);
	return frontmatter["disable-model-invocation"] === true;
}
