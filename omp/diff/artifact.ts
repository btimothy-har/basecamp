import { createHash } from "node:crypto";
import type { ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import type { UserNote } from "./hunk-cli.ts";
import type { DiffSnapshot } from "./loader.ts";

export type DiffReviewStatus = "submitted" | "cancelled";

/** The durable result of one transactional Hunk review. */
export interface DiffReviewArtifactV1 {
	schema_version: 1;
	repository: string;
	base_revision: string;
	head_revision: string;
	diff_sha256: string;
	status: DiffReviewStatus;
	user_annotations: UserNote[];
	displayed_agent_annotation_ids: string[];
	discarded_agent_annotation_ids: string[];
}

export interface PersistedDiffReview {
	artifact: DiffReviewArtifactV1;
	reviewRef: string;
	storage: "artifact" | "blob";
}

type ReviewSessionManager = Pick<
	ExtensionContext["sessionManager"],
	"getArtifactsDir" | "saveArtifact" | "getArtifactPath" | "putBlob"
>;

export function buildDiffReviewArtifact(
	snapshot: DiffSnapshot,
	status: DiffReviewStatus,
	userAnnotations: UserNote[],
	displayedAgentAnnotationIds: string[],
	discardedAgentAnnotationIds: string[],
): DiffReviewArtifactV1 {
	return {
		schema_version: 1,
		repository: snapshot.repository,
		base_revision: snapshot.baseRevision,
		head_revision: snapshot.headRevision,
		displayed_agent_annotation_ids: displayedAgentAnnotationIds,
		discarded_agent_annotation_ids: discardedAgentAnnotationIds,
		diff_sha256: createHash("sha256").update(snapshot.patch).digest("hex"),
		status,
		user_annotations: userAnnotations,
	};
}

/** Persist a completed review before its annotations are consumed. */
export async function persistDiffReview(
	sessionManager: ReviewSessionManager,
	artifact: DiffReviewArtifactV1,
): Promise<PersistedDiffReview> {
	const json = JSON.stringify(artifact, null, 2);
	if (sessionManager.getArtifactsDir() !== null) {
		const id = await sessionManager.saveArtifact(json, "diff-review");
		if (!id || (await sessionManager.getArtifactPath(id)) === null) {
			throw new Error("OMP could not persist the diff review artifact");
		}
		return { artifact, reviewRef: `artifact://${id}`, storage: "artifact" };
	}
	const blob = await sessionManager.putBlob(Buffer.from(json), { extension: "json" });
	return { artifact, reviewRef: blob.displayPath, storage: "blob" };
}
