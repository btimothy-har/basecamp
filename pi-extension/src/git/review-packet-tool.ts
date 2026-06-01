/**
 * review_packet tool — lets the LLM present a structured review packet for
 * interactive user walkthrough and receive consolidated feedback.
 *
 * This tool is read-only for repo/GitHub state. It only opens local UI and
 * persists the normalized packet plus review result to scratch.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getWorkspaceState } from "../platform/workspace";
import {
	type ConsolidatedReviewFeedback,
	normalizeReviewPacket,
	type ReviewPacket,
	ReviewPacketSchema,
	reviewFeedbackCategoryLabel,
} from "./review-packet";
import { type DisplayReviewPacket, resolveReviewPacketDiffs } from "./review-packet-diff";
import { type ReviewPacketReviewResult, showReviewPacket } from "./review-packet-review";
import { ensurePrivateDirectory, getScratchDir } from "./utils";

interface ReviewPacketTargetMetadata {
	kind: ReviewPacket["target"]["kind"];
	prNumber?: number;
	branch: string;
	base: string;
	headSha?: string;
	repoName?: string;
	repoRoot?: string;
	effectiveCwd: string;
	worktreeLabel?: string;
	worktreePath?: string;
}

interface ReviewPacketArtifact {
	createdAt: string;
	target: ReviewPacketTargetMetadata;
	packet: DisplayReviewPacket;
	reviewResult: ReviewPacketReviewResult;
}

interface ReviewPacketToolDetails {
	cancelled: boolean;
	feedback: ConsolidatedReviewFeedback[];
	artifactPath?: string;
	target?: ReviewPacketTargetMetadata;
	message?: string;
}

const PRIVATE_FILE_MODE = 0o600;

function isSubagent(): boolean {
	return Number.parseInt(process.env.BASECAMP_AGENT_DEPTH ?? "0", 10) > 0;
}

function targetMetadata(packet: ReviewPacket, cwd: string): ReviewPacketTargetMetadata {
	const workspace = getWorkspaceState();
	return {
		kind: packet.target.kind,
		prNumber: packet.target.prNumber,
		branch: packet.target.branch,
		base: packet.target.base,
		headSha: packet.target.headSha,
		repoName: workspace?.repo?.name,
		repoRoot: workspace?.protectedRoot ?? workspace?.repo?.root ?? undefined,
		effectiveCwd: workspace?.effectiveCwd ?? cwd,
		worktreeLabel: workspace?.activeWorktree?.label,
		worktreePath: workspace?.activeWorktree?.path,
	};
}

function targetSummary(target: ReviewPacketTargetMetadata): string {
	const sha = target.headSha ? ` @ ${target.headSha}` : "";
	if (target.kind === "pr") return `PR #${target.prNumber} ${target.branch} → ${target.base}${sha}`;
	return `${target.branch} → ${target.base}${sha}`;
}

function cardTitle(packet: ReviewPacket, cardId: string): string {
	return packet.cards.find((card) => card.id === cardId)?.title ?? cardId;
}

function feedbackSummary(packet: ReviewPacket, feedback: readonly ConsolidatedReviewFeedback[]): string[] {
	return feedback.map((item) => {
		const title = cardTitle(packet, item.cardId);
		const texts = item.texts.length > 0 ? ` — ${item.texts.join(" | ")}` : "";
		return `- ${item.cardId} (${reviewFeedbackCategoryLabel(item.category).toLowerCase()}): ${title}${texts}`;
	});
}

function ensureArtifactDir(cwd: string): string {
	const dir = path.join(getScratchDir(cwd), "review-packets");
	ensurePrivateDirectory(dir);
	return dir;
}

function persistArtifact(cwd: string, artifact: ReviewPacketArtifact): string {
	const dir = ensureArtifactDir(cwd);
	const filename = `review-packet-${Date.now()}-${crypto.randomBytes(8).toString("hex")}.json`;
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

function errorResult(message: string): {
	isError: true;
	details: ReviewPacketToolDetails;
	content: { type: "text"; text: string }[];
} {
	return {
		isError: true,
		details: {
			cancelled: false,
			feedback: [],
			message,
		},
		content: [{ type: "text", text: message }],
	};
}

export function registerReviewPacketTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "review_packet",
		label: "Review Packet",
		description:
			"Open an interactive review packet walkthrough for the user and return consolidated, structured feedback. " +
			"Read-only for repository and GitHub state; persists a JSON artifact under scratch.",
		promptSnippet: "Show a review packet walkthrough — user can provide per-card structured feedback",
		parameters: ReviewPacketSchema,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (!ctx.hasUI) {
				return errorResult(
					"review_packet requires an interactive UI and cannot run in this non-interactive/no-UI context.",
				);
			}

			if (isSubagent()) {
				return errorResult("review_packet is disabled in subagents because it opens user-facing UI.");
			}

			let packet: ReviewPacket;
			try {
				packet = normalizeReviewPacket(params as ReviewPacket);
			} catch (error) {
				return errorResult(`Invalid review packet: ${error instanceof Error ? error.message : String(error)}`);
			}

			const displayPacket = await resolveReviewPacketDiffs(pi, packet);
			const reviewResult = await showReviewPacket(displayPacket, ctx);
			const target = targetMetadata(displayPacket, ctx.cwd);
			const createdAt = new Date().toISOString();
			const artifactPath = persistArtifact(ctx.cwd, {
				createdAt,
				target,
				packet: displayPacket,
				reviewResult,
			});

			const details: ReviewPacketToolDetails = {
				cancelled: reviewResult.cancelled,
				feedback: reviewResult.feedback,
				artifactPath,
				target,
			};

			const textLines: string[] = [];
			if (reviewResult.cancelled) {
				textLines.push("User cancelled review packet walkthrough.");
			} else if (reviewResult.feedback.length === 0) {
				textLines.push("User submitted the review packet with no feedback.");
			} else {
				textLines.push("User feedback on review packet:", ...feedbackSummary(displayPacket, reviewResult.feedback));
			}
			textLines.push(`Target: ${targetSummary(target)}`, `Artifact: ${artifactPath}`);

			return {
				details,
				content: [{ type: "text" as const, text: textLines.join("\n") }],
			};
		},
	});
}
