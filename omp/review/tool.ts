import { type ExtensionAPI, Text, type Theme } from "@oh-my-pi/pi-coding-agent";
import { findRepoRoot } from "@oh-my-pi/pi-coding-agent/capability/fs";
import { buildReviewArtifact, prepareReview, reviewPriorityCounts } from "./artifact.ts";
import { navigateReviewFindings } from "./navigator/index.ts";
import { repositoryRelativePath } from "./paths.ts";
import {
	createReviewFindingsParameters,
	type FeedbackStatus,
	type OverallCorrectness,
	type PriorityCounts,
	type ReviewFindingsInput,
} from "./schema.ts";

const TOOL_DESCRIPTION =
	"Present one final code review after all native OMP reviewer tasks finish. The primary agent must validate and semantically deduplicate every finding before calling this tool exactly once. Explain the overall verdict, recommend what the user should do next, and give every surviving finding its own recommendation. Pass an empty findings array when no valid findings remain. This tool collects user feedback and returns a readable artifact URI or blob path; read it before continuing. Reviewer subagents must not call this tool.";

export interface ReviewToolDetails {
	commentedCount: number;
	counts: PriorityCounts;
	feedbackStatus: FeedbackStatus;
	explanation?: string;
	findingCount: number;
	overallCorrectness: OverallCorrectness;
	overallConfidence?: number;
	recommendation?: string;
	reviewRef: string;
	scope: string;
	storage: "artifact" | "blob";
}

function renderReviewResult(details: ReviewToolDetails, theme: Theme): string {
	let title: string;
	switch (details.feedbackStatus) {
		case "submitted":
			title = "Review feedback submitted";
			break;
		case "cancelled":
			title = "Review feedback cancelled";
			break;
		case "unavailable":
			title = "Interactive review unavailable";
			break;
		case "not_required":
			title = "Review complete";
			break;
	}
	const verdictColor = details.overallCorrectness === "correct" ? "success" : "error";
	const verdict = details.overallCorrectness === "correct" ? "Correct" : "Incorrect";
	const confidence =
		typeof details.overallConfidence === "number" && Number.isFinite(details.overallConfidence)
			? ` · ${Math.round(details.overallConfidence * 100)}% confidence`
			: "";
	const findings = `${details.findingCount} finding${details.findingCount === 1 ? "" : "s"}`;
	const comments = `${details.commentedCount} comment${details.commentedCount === 1 ? "" : "s"}`;
	const counts = details.counts;
	const location = `${theme.fg("muted", "Full review and feedback:")} ${details.reviewRef}`;
	const lines = [
		theme.fg("toolTitle", theme.bold(title)),
		`${theme.fg(verdictColor, verdict)}${confidence} · ${findings} · ${comments}`,
		`P0 ${counts[0]}   P1 ${counts[1]}   P2 ${counts[2]}   P3 ${counts[3]}`,
	];
	if (details.explanation) lines.push("", theme.fg("accent", theme.bold("Explanation")), details.explanation);
	if (details.recommendation) {
		lines.push("", theme.fg("accent", theme.bold("Overall recommendation")), details.recommendation);
	}
	lines.push("", location);
	return lines.join("\n");
}

export default function registerReviewTool(pi: ExtensionAPI): void {
	const parameters = createReviewFindingsParameters(pi.arktype);
	pi.registerTool<typeof parameters, ReviewToolDetails>({
		name: "review_findings",
		label: "Review findings",
		description: TOOL_DESCRIPTION,
		parameters,
		approval: "read",
		strict: true,
		loadMode: "essential",
		async execute(_toolCallId, rawParams, signal, _onUpdate, ctx) {
			const params = rawParams as ReviewFindingsInput;
			const repositoryRoot = await findRepoRoot(ctx.cwd);
			const prepared = prepareReview({
				...params,
				findings: params.findings.map((finding) => ({
					...finding,
					file_path: repositoryRelativePath(finding.file_path, repositoryRoot),
				})),
			});
			let feedbackStatus: FeedbackStatus;
			let comments: Record<string, string> = {};

			if (prepared.findings.length === 0) {
				feedbackStatus = "not_required";
			} else if (ctx.mode !== "tui") {
				feedbackStatus = "unavailable";
			} else {
				const navigation = await navigateReviewFindings(ctx.ui, prepared, signal);
				feedbackStatus = navigation.cancelled ? "cancelled" : "submitted";
				if (!navigation.cancelled) comments = navigation.comments;
			}

			const artifact = buildReviewArtifact(prepared, feedbackStatus, comments);
			const artifactJson = JSON.stringify(artifact, null, 2);
			let reviewRef: string;
			let storage: ReviewToolDetails["storage"];
			if (ctx.sessionManager.getArtifactsDir() !== null) {
				const artifactId = await ctx.sessionManager.saveArtifact(artifactJson, "code-review");
				if (!artifactId) throw new Error("OMP could not allocate a review artifact");
				reviewRef = `artifact://${artifactId}`;
				storage = "artifact";
			} else {
				const blob = await ctx.sessionManager.putBlob(Buffer.from(artifactJson), { extension: "json" });
				reviewRef = blob.displayPath;
				storage = "blob";
			}
			const details: ReviewToolDetails = {
				commentedCount: artifact.findings.filter((finding) => finding.feedback.comment !== null).length,
				counts: reviewPriorityCounts(artifact.findings),
				explanation: artifact.explanation,
				feedbackStatus,
				findingCount: artifact.findings.length,
				overallCorrectness: artifact.overall_correctness,
				overallConfidence: artifact.confidence,
				recommendation: artifact.recommendation,
				reviewRef,
				scope: artifact.scope,
				storage,
			};
			const reference = storage === "blob" ? JSON.stringify(reviewRef) : reviewRef;
			return {
				content: [{ type: "text", text: `Read ${reference} before continuing.` }],
				details,
			};
		},
		renderCall(args, options, theme) {
			const count = Array.isArray(args.findings) ? args.findings.length : 0;
			const suffix = options.isPartial ? "…" : ` ${count} finding${count === 1 ? "" : "s"}`;
			return new Text(`${theme.fg("toolTitle", theme.bold("review_findings"))}${theme.fg("muted", suffix)}`, 0, 0);
		},
		renderResult(result, _options, theme) {
			const fallback = result.content.find((part) => part.type === "text")?.text ?? "";
			return new Text(result.details ? renderReviewResult(result.details, theme) : fallback, 0, 0);
		},
	});
}
