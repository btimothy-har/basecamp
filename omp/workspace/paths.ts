/**
 * Path resolution for the canonical-checkout guard. All comparison is
 * component-wise on realpath-resolved paths so lookalike prefixes
 * (`/repo2` vs `/repo`) and symlinks cannot smuggle a canonical target past
 * the guard or false-positive a sibling directory.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { type LocalProtocolOptions, resolveLocalUrlToPath } from "@oh-my-pi/pi-coding-agent/internal-urls";
import { parseXdUrl } from "@oh-my-pi/pi-coding-agent/internal-urls/xd-protocol";
import {
	isInternalUrlPath,
	normalizeLocalScheme,
	parseSearchPath,
	peelWriteUrlSelector,
	resolveToCwd,
} from "@oh-my-pi/pi-coding-agent/tools/path-utils";
import { unwrapHashlineHeaderPath } from "@oh-my-pi/pi-coding-agent/tools/plan-mode-guard";
import { parseSqlitePathCandidates } from "@oh-my-pi/pi-coding-agent/tools/sqlite-reader";
import { parseArchivePathCandidates } from "@oh-my-pi/pi-utils/ar";

/** Canonical form of an existing root directory; lexical fallback when missing. */
export function normalizeRoot(root: string): string {
	try {
		return fs.realpathSync(root);
	} catch {
		return path.resolve(root);
	}
}

/**
 * Realpath `target`, walking to the nearest existing ancestor when the target
 * itself (or intermediate components) does not exist yet. This keeps symlink
 * resolution honest for paths a mutation is about to create.
 */
export function realpathNearest(target: string): string {
	return resolveNearest(path.resolve(target), new Set<string>());
}

function resolveNearest(target: string, seenLinks: Set<string>): string {
	const missing: string[] = [];
	let current = target;
	for (;;) {
		try {
			const real = fs.realpathSync(current);
			return missing.length === 0 ? real : path.join(real, ...missing.reverse());
		} catch {
			try {
				if (fs.lstatSync(current).isSymbolicLink()) {
					if (seenLinks.has(current)) return target;
					seenLinks.add(current);
					const link = fs.readlinkSync(current);
					const destination = path.resolve(path.dirname(current), link);
					return resolveNearest(path.join(destination, ...missing.reverse()), seenLinks);
				}
			} catch {
				// Continue toward the nearest existing ancestor.
			}
			const parent = path.dirname(current);
			if (parent === current) return target;
			missing.push(path.basename(current));
			current = parent;
		}
	}
}

/** True when `target` equals `root` or lives under it, compared per component. */
export function sameOrWithin(root: string, target: string): boolean {
	if (target === root) return true;
	const prefix = root.endsWith(path.sep) ? root : root + path.sep;
	return target.startsWith(prefix);
}

/**
 * Resolve a tool-supplied path against the live cwd (`~`, `..`, stray-`:`
 * prefix, Windows drive aliases all handled by the native helper) and resolve
 * symlinks. `local://` resolves through the calling session's artifact mapping;
 * other internal URLs and opaque devices remain owned by their native handlers.
 */
export function resolveFilesystemTarget(
	rawPath: string,
	cwd: string,
	localProtocolOptions?: LocalProtocolOptions,
): string | null {
	if (rawPath.length === 0) return null;
	const normalized = normalizeLocalScheme(rawPath);
	if (normalized.startsWith("local:")) {
		if (!localProtocolOptions) return null;
		try {
			return realpathNearest(resolveLocalUrlToPath(normalized, localProtocolOptions));
		} catch {
			return null;
		}
	}
	if (isInternalUrlPath(rawPath)) return null;
	let resolved: string;
	try {
		resolved = resolveToCwd(rawPath, cwd);
	} catch {
		// Unparseable input fails natively; it is not a guard target.
		return null;
	}
	return realpathNearest(resolved);
}

/**
 * Filesystem paths a `write` call may mutate. Unwraps hashline `[path#TAG]`
 * headers exactly like the write tool does, then:
 * - `xd://<device>` is the outer transport for a mounted tool; the inner
 *   device emits its own `tool_call`, so the write itself has no target.
 * - `local://` resolves through the calling session's filesystem mapping;
 *   other internal URLs remain owned by their native handlers.
 * - `archive.ext:member` and `db.sqlite:table` selectors mutate their
 *   container file, so every candidate container is a target alongside the
 *   literal path.
 */
export function collectWriteTargets(rawPath: string): string[] {
	const unwrapped = unwrapHashlineHeaderPath(rawPath);
	if (parseXdUrl(unwrapped)) return [];
	let peeled = unwrapped;
	try {
		peeled = peelWriteUrlSelector(unwrapped);
	} catch {
		// A malformed selector throws natively; guard the unpeeled path.
	}
	return collectContainerTargets(peeled);
}

/** Filesystem paths for a plain file target with archive/sqlite container splitting. */
export function collectContainerTargets(rawPath: string): string[] {
	if (rawPath.length === 0) return [];
	if (normalizeLocalScheme(rawPath).startsWith("local:")) return [rawPath];
	if (isInternalUrlPath(rawPath)) return [];
	const targets = new Set<string>([rawPath]);
	for (const candidate of parseArchivePathCandidates(rawPath)) {
		if (candidate.archivePath !== rawPath) targets.add(candidate.archivePath);
	}
	for (const candidate of parseSqlitePathCandidates(rawPath)) {
		if (candidate.sqlitePath !== rawPath) targets.add(candidate.sqlitePath);
	}
	return [...targets];
}

/**
 * Fixed prefix of an `ast_edit` scope entry (file, directory, or glob), or
 * null for internal-URL scopes the guard does not own. A glob's fixed prefix
 * is the directory portion before the first metacharacter segment.
 */
export function resolveScopePrefix(rawScope: string, cwd: string): string | null {
	return resolveFilesystemTarget(parseSearchPath(rawScope).basePath, cwd);
}
