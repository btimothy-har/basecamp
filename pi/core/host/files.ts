/**
 * Filesystem + JSON primitives shared across domains.
 *
 * The atomic writer and the plain reader were previously copied verbatim into
 * session-state, companion snapshots, and the tasks store; `isRecord` was
 * re-declared in five places. This is their single home. The two perms-hardened
 * writers (agent run-result, code-review artifacts) are deliberately NOT folded
 * in — they have different shapes (random-temp+rename vs O_EXCL fresh-create)
 * and security-sensitive perms.
 */

import * as fs from "node:fs";
import * as path from "node:path";

/** Narrow an unknown to a plain object — excludes `null` and arrays. */
export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Write `value` as pretty-printed JSON to `filePath` atomically: mkdir -p the
 * parent, write a sibling `.tmp`, then rename over the target.
 */
export function writeJsonFileAtomic(filePath: string, value: unknown): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(value, null, 2));
	fs.renameSync(tmp, filePath);
}

/**
 * Read + parse JSON from `filePath`, returning `null` when the file is missing
 * or its contents are not valid JSON. Callers layer their own schema checks on
 * top of the parsed value.
 */
export function readJsonFile<T = unknown>(filePath: string): T | null {
	let raw: string;
	try {
		raw = fs.readFileSync(filePath, "utf8");
	} catch {
		return null;
	}
	try {
		return JSON.parse(raw) as T;
	} catch {
		return null;
	}
}
