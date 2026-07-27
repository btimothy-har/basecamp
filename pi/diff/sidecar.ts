import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type Static, Type } from "@sinclair/typebox";

export const PRIVATE_FILE_MODE = 0o600;
export const PRIVATE_DIR_MODE = 0o700;

export const Annotation = Type.Object(
	{
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
 * always resolves to the same file — overwritten on each call, never appended.
 */
export function sidecarPath(worktreeDir: string): string {
	const digest = createHash("sha256").update(worktreeDir).digest("hex").slice(0, 16);
	const dir = path.join(scratchRoot(), "diff");
	return path.join(dir, `annotate-${digest}.json`);
}

export interface WriteResult {
	path: string;
	files: number;
	annotations: number;
}

export function writeSidecar(worktreeDir: string, summary: string, files: AnnotatedFile[]): WriteResult {
	const sidecar: Sidecar = {
		version: SIDECAR_VERSION,
		summary,
		files,
	};

	const filePath = sidecarPath(worktreeDir);
	const dir = path.dirname(filePath);
	fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE });
	fs.chmodSync(dir, PRIVATE_DIR_MODE);

	// O_TRUNC ensures overwrite semantics — a prior sidecar for this worktree
	// is replaced rather than appended to.
	const fd = fs.openSync(
		filePath,
		fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_TRUNC,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, `${JSON.stringify(sidecar, null, 2)}\n`, "utf8");
		fs.fchmodSync(fd, PRIVATE_FILE_MODE);
	} finally {
		fs.closeSync(fd);
	}

	const annotationCount = files.reduce((acc, f) => acc + f.annotations.length, 0);
	return { path: filePath, files: files.length, annotations: annotationCount };
}
