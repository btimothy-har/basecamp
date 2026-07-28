import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Static, Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";

export const PRIVATE_FILE_MODE = 0o600;
export const PRIVATE_DIR_MODE = 0o700;

export const Annotation = Type.Object(
	{
		/**
		 * Deterministic content key (see annotationId). hunk ignores JSON keys it
		 * does not know, so the id rides along in the sidecar hunk reads; it
		 * exists for dedupe on merge and for removeAnnotation.
		 */
		id: Type.Optional(Type.String({ minLength: 1 })),
		newRange: Type.Tuple([Type.Integer(), Type.Integer()]),
		summary: Type.String({ minLength: 1 }),
		rationale: Type.Optional(Type.String()),
	},
	{ additionalProperties: false },
);
export type Annotation = Static<typeof Annotation>;

export const AnnotatedFile = Type.Object(
	{
		path: Type.String({ minLength: 1 }),
		summary: Type.Optional(Type.String()),
		annotations: Type.Array(Annotation),
	},
	{ additionalProperties: false },
);
export type AnnotatedFile = Static<typeof AnnotatedFile>;

export const Sidecar = Type.Object(
	{
		version: Type.Literal(1),
		/**
		 * The review base these annotations were anchored against. hunk ignores
		 * keys it does not know, so the stamp rides along in the file it reads
		 * rather than in a second file that could drift away from it.
		 */
		basecampBase: Type.String({ minLength: 1 }),
		summary: Type.String({ minLength: 1 }),
		files: Type.Array(AnnotatedFile),
	},
	{ additionalProperties: false },
);
export type Sidecar = Static<typeof Sidecar>;

const SIDECAR_VERSION = 1;

function scratchRoot(): string {
	return process.env.BASECAMP_SCRATCH_DIR || os.tmpdir();
}

/**
 * Deterministic per-worktree sidecar path. The worktree dir is hashed (sha256,
 * first 16 hex chars) so two worktrees never collide and the same worktree
 * always resolves to the same file.
 *
 * Lifecycle: the agent annotates WHILE working, so writeSidecar accumulates
 * annotations across calls within one review span (same base); a new span
 * (different base) replaces the old one; /diff consumes the sidecar at review
 * close and clears it via clearSidecar. Individual annotations are removable
 * by id via removeAnnotation.
 */
export function sidecarPath(worktreeDir: string): string {
	const digest = createHash("sha256").update(worktreeDir).digest("hex").slice(0, 16);
	const dir = path.join(scratchRoot(), "diff");
	return path.join(dir, `annotate-${digest}.json`);
}

/**
 * Deterministic annotation key: sha256 of path, range, summary, and
 * rationale, first 12 hex chars. Same content → same key, so exact-duplicate
 * dedupe on merge is free; a corrected rationale yields a NEW key, so
 * rewording an annotation never silently collides with — or is silently
 * dropped in favour of — the wording it replaces. 12 chars (not 8) buys a
 * cheap collision margin.
 */
export function annotationId(
	filePath: string,
	newRange: [number, number],
	summary: string,
	rationale?: string,
): string {
	return createHash("sha256")
		.update(`${filePath}\n${newRange[0]}\n${newRange[1]}\n${summary}\n${rationale ?? ""}`)
		.digest("hex")
		.slice(0, 12);
}

export interface RecordedAnnotation {
	id: string;
	path: string;
	newRange: [number, number];
	summary: string;
}

export interface WriteResult {
	path: string;
	/** Total files in the sidecar after the write. */
	files: number;
	/** Total annotations in the sidecar after the write. */
	annotations: number;
	/** Annotations this call actually added (post-dedupe/supersession), in call order. */
	recorded: RecordedAnnotation[];
}

/**
 * The stored sidecar for this worktree, or null when there is none, it cannot
 * be read, or it does not parse as a current-version sidecar. Never throws.
 */
function readSidecar(worktreeDir: string): Sidecar | null {
	let parsed: unknown;
	try {
		parsed = JSON.parse(fs.readFileSync(sidecarPath(worktreeDir), "utf8"));
	} catch {
		return null;
	}
	return Value.Check(Sidecar, parsed) ? parsed : null;
}

/**
 * Every incoming annotation is stamped with its computed id — always computed,
 * never trusted from input — and, within one batch, exact duplicates collapse
 * to their first occurrence. Entries are folded by path: one entry per path,
 * annotations concatenated in encounter order, a later non-undefined per-file
 * summary winning — so one call can never write two entries for the same path
 * (which would leave later merges updating only the first, and the shared
 * path's annotations unremovable as ambiguous).
 */
function stampFiles(files: AnnotatedFile[]): AnnotatedFile[] {
	const seen = new Set<string>();
	const byPath = new Map<string, AnnotatedFile>();
	for (const f of files) {
		let entry = byPath.get(f.path);
		if (!entry) {
			entry = { path: f.path, annotations: [] };
			byPath.set(f.path, entry);
		}
		for (const a of f.annotations) {
			const id = annotationId(f.path, a.newRange, a.summary, a.rationale);
			if (seen.has(id)) continue;
			seen.add(id);
			entry.annotations.push({ ...a, id });
		}
		if (f.summary !== undefined) entry.summary = f.summary;
	}
	return [...byPath.values()];
}

/**
 * Atomic sidecar write: written aside and renamed so an interrupted write
 * cannot leave torn JSON at a path every later /diff would keep handing to
 * hunk. O_EXCL over a random name means the descriptor is always one this call
 * created, so the open mode alone decides permissions and the temp path is not
 * predictable enough to hijack.
 */
function writeSidecarFile(filePath: string, sidecar: Sidecar): void {
	const dir = path.dirname(filePath);
	fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE });
	// mkdirSync only applies mode on creation; re-enforce so a reused dir cannot stay looser.
	fs.chmodSync(dir, PRIVATE_DIR_MODE);

	const tempPath = `${filePath}.${randomBytes(6).toString("hex")}.tmp`;
	const fd = fs.openSync(
		tempPath,
		fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, `${JSON.stringify(sidecar, null, 2)}\n`, "utf8");
	} finally {
		fs.closeSync(fd);
	}
	fs.renameSync(tempPath, filePath);
}

/**
 * Merge incoming (already stamped) files into an existing sidecar of the same
 * review span: existing entries keep their annotations; a same-path incoming
 * entry appends annotations whose ids are not already present (exact
 * duplicates collapse) and, when it carries a summary, replaces the entry's
 * summary; new paths are added. The incoming top-level summary always wins.
 *
 * Supersession: the annotation id includes the rationale, so a corrected
 * rationale for the same path + range + summary arrives under a NEW id.
 * Rather than appending a near-duplicate, the incoming annotation REPLACES
 * the matching stored one in place — same position, new rationale and id —
 * which is what the "annotate again to reword" workflow promises.
 *
 * Returns the merged sidecar and the annotations this call actually
 * contributed (appended or superseding, in call order).
 */
function mergeSidecar(
	existing: Sidecar,
	incoming: AnnotatedFile[],
	summary: string,
): { sidecar: Sidecar; recorded: RecordedAnnotation[] } {
	const recorded: RecordedAnnotation[] = [];
	const files = existing.files.map((f) => ({ ...f, annotations: [...f.annotations] }));
	for (const incomingFile of incoming) {
		const entry = files.find((f) => f.path === incomingFile.path);
		if (!entry) {
			files.push({ ...incomingFile, annotations: [...incomingFile.annotations] });
			for (const a of incomingFile.annotations) {
				recorded.push({ id: a.id ?? "", path: incomingFile.path, newRange: a.newRange, summary: a.summary });
			}
			continue;
		}
		const present = new Set(
			entry.annotations.map((a) => a.id ?? annotationId(entry.path, a.newRange, a.summary, a.rationale)),
		);
		for (const a of incomingFile.annotations) {
			// Stamped incoming annotations always carry an id; compute as a fallback for untyped callers.
			const id = a.id ?? annotationId(incomingFile.path, a.newRange, a.summary, a.rationale);
			if (present.has(id)) continue; // Exact duplicate — collapse.
			const superseded = entry.annotations.findIndex(
				(stored) =>
					stored.newRange[0] === a.newRange[0] && stored.newRange[1] === a.newRange[1] && stored.summary === a.summary,
			);
			if (superseded >= 0) {
				present.delete(entry.annotations[superseded]?.id ?? "");
				entry.annotations[superseded] = a;
			} else {
				entry.annotations.push(a);
			}
			present.add(id);
			recorded.push({ id, path: incomingFile.path, newRange: a.newRange, summary: a.summary });
		}
		if (incomingFile.summary !== undefined) entry.summary = incomingFile.summary;
	}
	return { sidecar: { ...existing, summary, files }, recorded };
}

/**
 * Record annotations for a worktree's changeset. Within one review span (same
 * base) calls MERGE into the existing sidecar — the agent annotates while
 * working, so annotations accumulate between reviews. Across spans (different
 * base) the files are REPLACED entirely: old annotations describe a different
 * diff span, and /diff clears the sidecar at review close, so anything
 * carrying an older anchor was never reviewed and must not leak into the next
 * span. An unparsable or wrong-version existing sidecar is overwritten fresh —
 * reading a sidecar never throws here.
 */
export function writeSidecar(worktreeDir: string, base: string, summary: string, files: AnnotatedFile[]): WriteResult {
	const incoming = stampFiles(files);
	const existing = readSidecar(worktreeDir);

	let sidecar: Sidecar;
	let recorded: RecordedAnnotation[];
	if (existing !== null && existing.basecampBase === base) {
		({ sidecar, recorded } = mergeSidecar(existing, incoming, summary));
	} else {
		sidecar = { version: SIDECAR_VERSION, basecampBase: base, summary, files: incoming };
		recorded = incoming.flatMap((f) =>
			f.annotations.map((a) => ({ id: a.id ?? "", path: f.path, newRange: a.newRange, summary: a.summary })),
		);
	}

	const filePath = sidecarPath(worktreeDir);
	writeSidecarFile(filePath, sidecar);

	const annotationCount = sidecar.files.reduce((acc, f) => acc + f.annotations.length, 0);
	return { path: filePath, files: sidecar.files.length, annotations: annotationCount, recorded };
}

/**
 * Remove the sidecar for a worktree — called by /diff once it has consumed the
 * annotations at review close. Never throws for a missing file.
 */
export function clearSidecar(worktreeDir: string): void {
	fs.rmSync(sidecarPath(worktreeDir), { force: true });
}

/**
 * Remove one annotation by id. Refuses when the key matches more than one
 * annotation (ambiguous). A file entry whose annotations empty out is pruned;
 * when the last file goes, the sidecar itself is deleted rather than left as
 * an empty husk /diff would hand hunk.
 */
export function removeAnnotation(
	worktreeDir: string,
	key: string,
): { removed: true } | { removed: false; reason: string } {
	const sidecar = readSidecar(worktreeDir);
	if (!sidecar) {
		return { removed: false, reason: "no annotations recorded for this worktree" };
	}

	let matches = 0;
	for (const f of sidecar.files) {
		for (const a of f.annotations) {
			if (a.id === key) matches += 1;
		}
	}
	if (matches === 0) {
		return { removed: false, reason: `annotation ${key} not found (already reviewed?)` };
	}
	if (matches > 1) {
		return { removed: false, reason: `annotation key ${key} is ambiguous` };
	}

	const files = sidecar.files
		.map((f) => ({ ...f, annotations: f.annotations.filter((a) => a.id !== key) }))
		.filter((f) => f.annotations.length > 0);

	const filePath = sidecarPath(worktreeDir);
	if (files.length === 0) {
		fs.rmSync(filePath, { force: true });
	} else {
		writeSidecarFile(filePath, { ...sidecar, files });
	}
	return { removed: true };
}

/**
 * The base a stored sidecar was written against, or null when there is none,
 * it cannot be read, or it predates stamping. A sidecar outlives the changeset
 * that produced it — worktree directories are deliberately reused across
 * branches — so the caller compares this before rendering stale rationale.
 */
export function readSidecarBase(worktreeDir: string): string | null {
	return readSidecar(worktreeDir)?.basecampBase ?? null;
}
