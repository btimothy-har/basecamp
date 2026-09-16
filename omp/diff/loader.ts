/**
 * Canonical diff loading for `/diff`: one resolver for the review scope —
 * merge-base(default branch, HEAD) through the current working tree — so the
 * read_diff tool, the annotation tools, and the Hunk projection never
 * disagree about what is being reviewed.
 */

import { lstat } from "node:fs/promises";
import { basename, posix, resolve, win32 } from "node:path";
import { requireGit } from "@oh-my-pi/pi-natives/vcs";
import { parseUntrackedPorcelain, relabelNoIndexPatch } from "./untracked.ts";

/** A 1-based inclusive line range on the NEW side of the diff. */
export interface DiffRange {
	start: number;
	end: number;
}

/** One file in a loaded diff, including the exact new-side lines Hunk will display. */
export interface DiffFile {
	path: string;
	newRanges: DiffRange[];
	newLines: ReadonlyMap<number, string>;
}

/** A loaded diff with the revisions and repository identity it was taken against. */
export interface DiffSnapshot {
	repositoryRoot: string;
	repository: string;
	defaultBranch: string;
	baseRevision: string;
	headRevision: string;
	patch: string;
	/** Non-file untracked entries omitted from this frozen patch. */
	warnings?: string[];
	files: DiffFile[];
}

export interface LoadDiffOptions {
	/** Repo-relative path filters; omit or pass an empty array for the full diff. */
	paths?: string[];
	signal?: AbortSignal;
}

export type LoadDiff = (cwd: string, options?: LoadDiffOptions) => Promise<DiffSnapshot>;

/** The slice of the VCS layer the loader needs. Tests substitute a fake. */
export interface DiffRepository {
	repositoryRoot(): string;
	repositoryIdentity(): string;
	defaultBranch(signal?: AbortSignal): Promise<string | null | undefined>;
	refExists(name: string, signal?: AbortSignal): Promise<boolean>;
	headSha(signal?: AbortSignal): Promise<string | null | undefined>;
	mergeBase(a: string, b: string, signal?: AbortSignal): Promise<string | null | undefined>;
	untrackedPaths(paths: string[] | undefined, signal?: AbortSignal): Promise<string[]>;
	untrackedDiff(path: string, signal?: AbortSignal): Promise<string | null>;
	diffText(options: { base: string; files?: string[] }, signal?: AbortSignal): Promise<string>;
}

export interface DiffLoaderDeps {
	openRepository(cwd: string): DiffRepository;
	/** Canonical repository identity stamped by Basecamp when available. */
	env?: { BASECAMP_REPO?: string | undefined };
}

function nativesRepository(cwd: string): DiffRepository {
	const repo = requireGit(cwd);
	const repositoryRoot = repo.info().repoRoot;
	return {
		repositoryRoot: () => repositoryRoot,
		repositoryIdentity: () => basename(repo.primaryRoot()),
		defaultBranch: (signal) => repo.defaultBranch(signal),
		refExists: (name, signal) => repo.refExists(name, signal),
		headSha: (signal) => repo.headSha(signal),
		mergeBase: (a, b, signal) => repo.mergeBase(a, b, signal),
		diffText: (options, signal) => repo.diffText(options, signal),
		untrackedPaths: async (paths, signal) => {
			const status = await repo.statusPorcelain(
				{
					untracked: "all",
					nulTerminated: true,
					...(paths && paths.length > 0 ? { pathspecs: paths } : {}),
				},
				signal,
			);
			return parseUntrackedPorcelain(status);
		},
		untrackedDiff: async (path, signal) => {
			const absolutePath = resolve(repositoryRoot, path);
			const metadata = await lstat(absolutePath);
			if (!metadata.isFile() && !metadata.isSymbolicLink()) return null;
			return relabelNoIndexPatch(await repo.diffNoIndex("/dev/null", absolutePath, true, signal), path);
		},
	};
}

/**
 * Validate and normalize one repo-relative path filter. Filters reach git as
 * pathspecs, so anything that could escape the repository is rejected here
 * rather than left to the backend's error text.
 */
function validateDiffPath(raw: string): string {
	if (raw.trim().length === 0) throw new Error("diff path filters must be non-empty");
	if (raw.includes("\0")) throw new Error(`diff path filter ${JSON.stringify(raw)} contains a NUL byte`);
	if (posix.isAbsolute(raw) || win32.isAbsolute(raw)) {
		throw new Error(`diff path filter ${JSON.stringify(raw)} is absolute; paths must be repository-relative`);
	}
	// Split on both separators: a `..\x` filter is a legitimate file name on
	// POSIX but a traversal attempt everywhere else, so reject it outright.
	for (const segment of raw.split(/[\\/]/)) {
		if (segment === "..") {
			throw new Error(`diff path filter ${JSON.stringify(raw)} escapes the repository: ".." segments are not allowed`);
		}
	}
	const normalized = posix.normalize(raw).replace(/\/+$/, "");
	if (normalized === "." || normalized === "") {
		throw new Error(`diff path filter ${JSON.stringify(raw)} does not name a path inside the repository`);
	}
	return normalized;
}

async function resolveDefaultBranch(repo: DiffRepository, signal?: AbortSignal): Promise<string> {
	const detected = (await repo.defaultBranch(signal))?.trim();
	if (detected) return detected;
	if (await repo.refExists("main", signal)) return "main";
	if (await repo.refExists("master", signal)) return "master";
	throw new Error("could not determine the repository's default branch (expected origin/HEAD, main, or master)");
}

const HUNK_HEADER = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/;

/** Decode git's C-style quoted path (octal escapes carry raw UTF-8 bytes). */
function unquoteGitPath(quoted: string): string {
	const bytes: number[] = [];
	const pushChar = (ch: string) => {
		for (const byte of Buffer.from(ch, "utf8")) bytes.push(byte);
	};
	for (let index = 1; index < quoted.length - 1; index++) {
		const ch = quoted.charAt(index);
		if (ch !== "\\") {
			pushChar(ch);
			continue;
		}
		index++;
		const octal = quoted.slice(index, index + 3);
		if (/^[0-7]{3}$/.test(octal)) {
			bytes.push(Number.parseInt(octal, 8));
			index += 2;
			continue;
		}
		switch (quoted.charAt(index)) {
			case "a":
				bytes.push(7);
				break;
			case "b":
				bytes.push(8);
				break;
			case "f":
				bytes.push(12);
				break;
			case "n":
				bytes.push(10);
				break;
			case "r":
				bytes.push(13);
				break;
			case "t":
				bytes.push(9);
				break;
			case "v":
				bytes.push(11);
				break;
			default:
				pushChar(quoted.charAt(index));
		}
	}
	return Buffer.from(bytes).toString("utf8");
}

/** Path from a `--- `/`+++ ` marker line; null for `/dev/null`. */
function parseMarkerPath(raw: string, prefix: "a/" | "b/"): string | null {
	if (raw === "/dev/null") return null;
	const path = raw.startsWith('"') ? unquoteGitPath(raw) : raw;
	return path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

/**
 * Split a unified patch into files with their inclusive new-side ranges. File
 * sections without `---`/`+++` markers (pure mode changes, 100%-similarity
 * renames) carry no anchorable lines and are omitted. Marker lines are only
 * recognized before a section's first hunk header, so added content that
 * happens to start with `++ ` is never mistaken for one.
 */
interface ParsedDiffFile extends DiffFile {
	newLines: Map<number, string>;
}

function parseDiffFiles(patch: string): DiffFile[] {
	const files: DiffFile[] = [];
	let current: ParsedDiffFile | null = null;
	let oldPath: string | null = null;
	let newLine: number | null = null;
	let scanningMarkers = false;
	for (const line of patch.split("\n")) {
		if (line.startsWith("diff --git ")) {
			current = null;
			oldPath = null;
			newLine = null;
			scanningMarkers = true;
			continue;
		}
		if (scanningMarkers && line.startsWith("--- ")) {
			oldPath = parseMarkerPath(line.slice("--- ".length), "a/");
			continue;
		}
		if (scanningMarkers && line.startsWith("+++ ")) {
			const path = parseMarkerPath(line.slice("+++ ".length), "b/") ?? oldPath;
			current = path === null ? null : { path, newRanges: [], newLines: new Map() };
			if (current !== null) files.push(current);
			continue;
		}
		const hunk = HUNK_HEADER.exec(line);
		if (hunk) {
			scanningMarkers = false;
			newLine = Number(hunk[1]);
			if (current === null) continue;
			const count = hunk[2] === undefined ? 1 : Number(hunk[2]);
			if (count > 0) current.newRanges.push({ start: newLine, end: newLine + count - 1 });
			continue;
		}
		if (current === null || newLine === null) continue;
		const marker = line.charAt(0);
		if (marker === "+" || marker === " ") {
			const content = line.slice(1);
			current.newLines.set(newLine, content.endsWith("\r") ? content.slice(0, -1) : content);
			newLine += 1;
		} else if (marker !== "-" && marker !== "\\") {
			newLine = null;
		}
	}
	return files;
}
function appendPatch(target: string, addition: string): string {
	if (addition.length === 0) return target;
	if (target.length === 0 || target.endsWith("\n")) return target + addition;
	return `${target}\n${addition}`;
}

function omitPatchPaths(patch: string, omittedPaths: ReadonlySet<string>): string {
	if (omittedPaths.size === 0) return patch;
	return patch
		.split(/(?=^diff --git )/m)
		.filter((section) => {
			const [file] = parseDiffFiles(section);
			return !file || !omittedPaths.has(file.path);
		})
		.join("");
}

export function createDiffLoader(deps: DiffLoaderDeps): LoadDiff {
	return async (cwd, options = {}) => {
		const signal = options.signal;
		const paths = options.paths?.map(validateDiffPath);
		const repo = deps.openRepository(cwd);
		const repositoryRoot = repo.repositoryRoot();
		const defaultBranch = await resolveDefaultBranch(repo, signal);
		const headRevision = await repo.headSha(signal);
		if (!headRevision) throw new Error("cannot load a diff: the repository has no commits (HEAD is unborn)");
		// Prefer the remote-tracking ref: nothing here ever fetches, so a local
		// default branch left behind by an earlier pull would place the base
		// before the real branch point and silently pull upstream commits in.
		const baseRef = (await repo.refExists(`origin/${defaultBranch}`, signal))
			? `origin/${defaultBranch}`
			: defaultBranch;
		const baseRevision = await repo.mergeBase(baseRef, "HEAD", signal);
		if (!baseRevision) throw new Error(`could not resolve a merge base between ${baseRef} and HEAD`);
		let patch = await repo.diffText(
			paths && paths.length > 0 ? { base: baseRevision, files: paths } : { base: baseRevision },
			signal,
		);
		const warnings: string[] = [];
		const untrackedPatches: Array<{ path: string; patch: string }> = [];
		const untrackedPaths = await repo.untrackedPaths(paths, signal);
		for (const path of untrackedPaths.sort()) {
			let untrackedPatch: string | null;
			try {
				untrackedPatch = await repo.untrackedDiff(path, signal);
			} catch (error) {
				const reason = error instanceof Error ? error.message : String(error);
				warnings.push(`Untracked path ${JSON.stringify(path)} was omitted because it could not be read: ${reason}`);
				continue;
			}
			if (untrackedPatch === null) {
				warnings.push(
					`Untracked directory ${JSON.stringify(path)} was omitted; embedded repositories are not expanded.`,
				);
			} else if (untrackedPatch.length > 0) {
				untrackedPatches.push({ path, patch: untrackedPatch });
			}
		}
		patch = omitPatchPaths(patch, new Set(untrackedPatches.map((entry) => entry.path)));
		for (const untracked of untrackedPatches) patch = appendPatch(patch, untracked.patch);
		const configuredName = (deps.env ?? process.env).BASECAMP_REPO?.trim();
		return {
			repositoryRoot,
			repository: configuredName || repo.repositoryIdentity(),
			defaultBranch,
			baseRevision,
			headRevision,
			patch,
			warnings,
			files: parseDiffFiles(patch),
		};
	};
}

export const loadDiff: LoadDiff = createDiffLoader({ openRepository: nativesRepository });
