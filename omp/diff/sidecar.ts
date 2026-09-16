/**
 * Writes the private, launch-only files Hunk needs for one frozen review:
 * the exact patch snapshot and the projection of validated agent rationale.
 * Neither file is state; the OMP journal and diff-review artifact own that.
 */

import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { DiffAnnotation } from "./annotations.ts";

export const AGENT_CONTEXT_VERSION = 1;
export const PRIVATE_FILE_MODE = 0o600;
export const PRIVATE_DIR_MODE = 0o700;

interface ProjectedAnnotation {
	/** Hunk reads ranges as [start, end] tuples, both inclusive. */
	newRange: [number, number];
	summary: string;
	rationale?: string;
}

interface ProjectedFile {
	path: string;
	annotations: ProjectedAnnotation[];
}

/** The exact document handed to hunk; nothing extra rides along. */
export interface AgentContextProjection {
	version: typeof AGENT_CONTEXT_VERSION;
	summary: string;
	files: ProjectedFile[];
}

export interface TemporaryHunkFile {
	readonly path: string;
	cleanup(): void;
}

export interface AgentContextHandle extends TemporaryHunkFile {
	/** Absolute path of the temporary file to pass as `--agent-context`. */
	readonly path: string;
	/** Annotations projected into the file. */
	readonly annotations: number;
	/** Delete the temporary file; never throws for a missing file. */
	cleanup(): void;
}

function toProjectedAnnotation(annotation: DiffAnnotation): ProjectedAnnotation {
	const { start, end } = annotation.newRange;
	if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) {
		throw new Error(`annotation ${annotation.id} has an invalid newRange [${start}, ${end}]`);
	}
	if (!annotation.path.trim()) {
		throw new Error(`annotation ${annotation.id} has an empty path`);
	}
	const projected: ProjectedAnnotation = { newRange: [start, end], summary: annotation.summary };
	if (annotation.rationale !== undefined) projected.rationale = annotation.rationale;
	return projected;
}

/**
 * Group annotations by path into hunk's agent-context shape, preserving
 * first-seen file order and input order within a file.
 *
 * The batch must target exactly one repository: the file lands in one hunk
 * session on one worktree, and projecting two repositories into it would
 * attach the other repository's rationale to this one's lines. An empty batch
 * is refused too — the orchestrator should launch without `--agent-context`
 * rather than hand hunk an empty context.
 */
export function projectAgentContext(annotations: readonly DiffAnnotation[], summary: string): AgentContextProjection {
	if (annotations.length === 0) {
		throw new Error("agent context requires at least one annotation");
	}
	const repository = annotations[0]?.repository;
	if (annotations.some((annotation) => annotation.repository !== repository)) {
		throw new Error("agent context cannot mix annotations from multiple repositories");
	}
	const files: ProjectedFile[] = [];
	const byPath = new Map<string, ProjectedFile>();
	for (const annotation of annotations) {
		let file = byPath.get(annotation.path);
		if (!file) {
			file = { path: annotation.path, annotations: [] };
			byPath.set(annotation.path, file);
			files.push(file);
		}
		file.annotations.push(toProjectedAnnotation(annotation));
	}
	return { version: AGENT_CONTEXT_VERSION, summary, files };
}

function writePrivateHunkFile(prefix: string, extension: string, content: string): TemporaryHunkFile {
	const dir = path.join(process.env.BASECAMP_SCRATCH_DIR || os.tmpdir(), "diff");
	fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE });
	// mkdirSync only applies mode on creation; re-enforce so a reused dir cannot stay looser.
	fs.chmodSync(dir, PRIVATE_DIR_MODE);
	const filePath = path.join(dir, `${prefix}-${randomBytes(8).toString("hex")}.${extension}`);
	const fd = fs.openSync(
		filePath,
		fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, content, "utf8");
	} catch (err) {
		fs.rmSync(filePath, { force: true });
		throw err;
	} finally {
		fs.closeSync(fd);
	}
	return {
		path: filePath,
		cleanup: () => {
			fs.rmSync(filePath, { force: true });
		},
	};
}

/** Freeze the exact patch loaded and validated by OMP for `hunk patch`. */
export function writeReviewPatch(patch: string): TemporaryHunkFile {
	if (patch.length === 0) throw new Error("cannot write an empty diff review");
	return writePrivateHunkFile("review", "patch", patch);
}

/**
 * Write the projection to a fresh private temporary file. O_EXCL over a
 * random name means the descriptor is always one this call created, so the
 * open mode alone decides permissions and the path is not predictable enough
 * to hijack.
 */
export function writeAgentContext(
	annotations: readonly DiffAnnotation[],
	options?: { summary?: string },
): AgentContextHandle {
	const projection = projectAgentContext(
		annotations,
		options?.summary ?? `Agent annotations (${annotations.length} recorded)`,
	);
	const temporaryFile = writePrivateHunkFile("agent-context", "json", `${JSON.stringify(projection, null, 2)}\n`);

	const count = projection.files.reduce((total, file) => total + file.annotations.length, 0);
	return {
		...temporaryFile,
		annotations: count,
	};
}
