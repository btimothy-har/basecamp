import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Finding, ReviewScope } from "./findings.ts";
import type { Verdict } from "./synthesis.ts";

export interface ReviewResult {
	scope: ReviewScope;
	summary: string;
	verdict: Verdict;
	findings: Finding[];
	createdAt: string;
}

interface AnnotatedFinding extends Finding {
	reaction: string | null;
}

interface ReviewArtifact extends Omit<ReviewResult, "findings"> {
	findings: AnnotatedFinding[];
}

export const PRIVATE_FILE_MODE = 0o600;
export const PRIVATE_DIR_MODE = 0o700;

export function persistReviewArtifact(result: ReviewResult, reactions: (string | null)[] | null): string {
	const findings: AnnotatedFinding[] = result.findings.map((finding, index) => ({
		...finding,
		reaction: reactions?.[index] ?? null,
	}));
	const artifact: ReviewArtifact = {
		scope: result.scope,
		summary: result.summary,
		verdict: result.verdict,
		findings,
		createdAt: result.createdAt,
	};

	const dir = path.join(process.env.BASECAMP_SCRATCH_DIR || os.tmpdir(), "code-review");
	fs.mkdirSync(dir, { recursive: true, mode: PRIVATE_DIR_MODE });
	// mkdirSync only applies mode on creation; re-enforce it so a reused dir can't keep looser perms.
	fs.chmodSync(dir, PRIVATE_DIR_MODE);
	const filename = `review-${Date.now()}-${randomBytes(4).toString("hex")}.json`;
	const artifactPath = path.join(dir, filename);
	const fd = fs.openSync(
		artifactPath,
		fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
		fs.fchmodSync(fd, PRIVATE_FILE_MODE);
	} finally {
		fs.closeSync(fd);
	}
	return artifactPath;
}
