import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Finding } from "./findings.ts";
import type { ReviewResult } from "./orchestrate.ts";

interface AnnotatedFinding extends Finding {
	reaction: string | null;
}

interface ReviewArtifact {
	scope: ReviewResult["scope"];
	verdict: ReviewResult["verdict"];
	findings: AnnotatedFinding[];
	createdAt: string;
}

export const PRIVATE_FILE_MODE = 0o600;
export const PRIVATE_DIR_MODE = 0o700;

export function isSubagent(): boolean {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	return Number.isFinite(depth) && depth > 0;
}

export function persistReviewArtifact(result: ReviewResult, reactions: (string | null)[] | null): string {
	const findings: AnnotatedFinding[] = result.findings.map((finding, index) => ({
		...finding,
		reaction: reactions?.[index] ?? null,
	}));
	const artifact: ReviewArtifact = {
		scope: result.scope,
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
		fs.chmodSync(artifactPath, PRIVATE_FILE_MODE);
	} finally {
		fs.closeSync(fd);
	}
	return artifactPath;
}
