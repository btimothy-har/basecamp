import { createHash, randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Static, Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import { mergeSidecar, type RecordedAnnotation, stampFiles } from "./sidecar-merge.ts";

export { annotationId, type RecordedAnnotation } from "./sidecar-merge.ts";

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
 * Read-modify-write here is **deliberately synchronous end to end**, and that is
 * what makes it safe under pi's parallel tool execution (`toolExecution`
 * defaults to "parallel"): two `annotate_changeset` calls in one assistant turn
 * run concurrently, but neither can interleave the other's read and write, so
 * the second always observes the first's state and merges onto it. Introducing
 * an `await` in this path — switching to `fs/promises`, say — would open exactly
 * the lost-update race that the framework's own edit tool needs
 * `withFileMutationQueue` to close, because its critical section is async. Keep
 * this one synchronous, or adopt the queue.
 *
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
			f.annotations.map((a) => ({ id: a.id, path: f.path, newRange: a.newRange, summary: a.summary })),
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
