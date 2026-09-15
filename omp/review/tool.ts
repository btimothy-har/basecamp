import { isAbsolute, relative, sep } from "node:path";
import { type ExtensionAPI, Text, type Theme } from "@oh-my-pi/pi-coding-agent";
import { buildReviewArtifact, prepareReview, reviewPriorityCounts } from "./artifact.ts";
import { navigateReviewFindings } from "./navigator/index.ts";
import {
	createReviewFindingsParameters,
	type FeedbackStatus,
	type OverallCorrectness,
	type PriorityCounts,
	type ReviewFindingsInput,
} from "./schema.ts";

const TOOL_DESCRIPTION =
	"Present one final code review after all native OMP reviewer tasks finish. The primary agent must validate and semantically deduplicate every finding before calling this tool exactly once. Pass OMP-native priorities and source locations, with an empty findings array when no valid findings remain. This tool collects user feedback and returns an artifact URI to read before continuing, or the complete JSON inline in a non-persistent session. Reviewer subagents must not call this tool.";

export interface ReviewToolDetails {
	artifactPersistent: boolean;
	artifactRef: string;
	commentedCount: number;
	counts: PriorityCounts;
	feedbackStatus: FeedbackStatus;
	findingCount: number;
	overallCorrectness: OverallCorrectness;
	scope: string;
}

function repositoryRelativePath(filePath: string, cwd: string): string {
	if (!isAbsolute(filePath)) return filePath;
	return relative(cwd, filePath).split(sep).join("/");
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
	const findings = `${details.findingCount} finding${details.findingCount === 1 ? "" : "s"}`;
	const comments = `${details.commentedCount} comment${details.commentedCount === 1 ? "" : "s"}`;
	const counts = details.counts;
	const location = details.artifactPersistent
		? `${theme.fg("muted", "Full review and feedback:")} ${details.artifactRef}`
		: theme.fg("muted", "Full review and feedback returned inline for this non-persistent session.");
	return [
		theme.fg("toolTitle", theme.bold(title)),
		`${theme.fg(verdictColor, verdict)} · ${findings} · ${comments}`,
		`P0 ${counts[0]}   P1 ${counts[1]}   P2 ${counts[2]}   P3 ${counts[3]}`,
		"",
		location,
	].join("\n");
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
			const prepared = prepareReview({
				...params,
				findings: params.findings.map((finding) => ({
					...finding,
					file_path: repositoryRelativePath(finding.file_path, ctx.cwd),
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
			const artifactId = await ctx.sessionManager.saveArtifact(artifactJson, "code-review");
			if (!artifactId) throw new Error("OMP could not allocate a review artifact");
			const artifactRef = `artifact://${artifactId}`;
			const artifactPersistent = (await ctx.sessionManager.getArtifactPath(artifactId)) !== null;
			const details: ReviewToolDetails = {
				artifactPersistent,
				artifactRef,
				commentedCount: artifact.findings.filter((finding) => finding.feedback.comment !== null).length,
				counts: reviewPriorityCounts(artifact.findings),
				feedbackStatus,
				findingCount: artifact.findings.length,
				overallCorrectness: artifact.overall_correctness,
				scope: artifact.scope,
			};
			// OMP 18.2.0 spills tool text above 50 KiB through the same unreadable
			// in-memory artifact path. Keep the expected-small fallback to bare JSON.
			const text = artifactPersistent ? `Read ${artifactRef} before continuing.` : artifactJson;
			return {
				content: [{ type: "text", text }],
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
