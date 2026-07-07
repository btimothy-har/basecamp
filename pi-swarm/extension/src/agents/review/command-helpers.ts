import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ReviewResult } from "./orchestrate.ts";

export const PRIVATE_FILE_MODE = 0o600;

export function isSubagent(): boolean {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	return Number.isFinite(depth) && depth > 0;
}

export function persistReviewArtifact(result: ReviewResult): string {
	const dir = path.join(process.env.BASECAMP_SCRATCH_DIR || os.tmpdir(), "code-review");
	fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
	const filename = `review-${Date.now()}-${randomBytes(4).toString("hex")}.json`;
	const artifactPath = path.join(dir, filename);
	const fd = fs.openSync(
		artifactPath,
		fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, `${JSON.stringify(result, null, 2)}\n`, "utf8");
		fs.chmodSync(artifactPath, PRIVATE_FILE_MODE);
	} finally {
		fs.closeSync(fd);
	}
	return artifactPath;
}
