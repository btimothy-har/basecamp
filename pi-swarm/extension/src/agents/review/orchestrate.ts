import { errorMessage } from "../errors.ts";
import type { Dimension, Finding } from "./findings.ts";
import { computeVerdict, mergeFindings, type Verdict } from "./synthesis.ts";

export interface ReviewScope {
	base: string;
	mergeBase: string;
	cwd: string;
	label: string;
}

export interface ReviewerSpec {
	agent: string;
	dimension: Dimension;
}

export const REVIEWERS: ReviewerSpec[] = [
	{ agent: "security-specialist", dimension: "security" },
	{ agent: "testing-specialist", dimension: "testing" },
	{ agent: "docs-specialist", dimension: "docs" },
	{ agent: "code-clarity-specialist", dimension: "clarity" },
	{ agent: "conventions-specialist", dimension: "conventions" },
	{ agent: "general-reviewer", dimension: "general" },
];

export type ReviewerStatus = "completed" | "failed" | "running" | "unknown";

export interface ReviewerWaitResult {
	status: ReviewerStatus;
	result: string | null;
	error: string | null;
}

export interface ReviewResult {
	scope: ReviewScope;
	verdict: Verdict;
	findings: Finding[];
	createdAt: string;
}

export type RunReviewResult =
	| { ok: true; result: ReviewResult }
	| { ok: false; failedReviewer: string; reason: string };

export interface OrchestrateDeps {
	dispatchReviewer: (spec: ReviewerSpec, brief: string) => Promise<string>;
	waitForReviewers: (handles: string[]) => Promise<Map<string, ReviewerWaitResult>>;
	transpose: (output: string, dimension: Dimension) => Promise<Finding[]>;
	now?: () => Date;
}

interface DispatchedReviewer {
	spec: ReviewerSpec;
	handle: string;
}

class ReviewerFailure extends Error {
	readonly agent: string;
	readonly reason: string;

	constructor(agent: string, reason: string) {
		super(reason);
		this.agent = agent;
		this.reason = reason;
	}
}

export function buildReviewerBrief(scope: ReviewScope): string {
	return `Review the code changes on this branch (base ${scope.base}) in the working directory ${scope.cwd}, including any uncommitted work. Run git yourself: \`git diff ${scope.mergeBase}\` shows every committed and uncommitted change since the branch diverged; also run \`git status --short\` for untracked files and read the changed and added files directly. Assess only what your specialist role covers. Report findings only — do not modify files or write fixes.`;
}

export async function runReview(scope: ReviewScope, deps: OrchestrateDeps): Promise<RunReviewResult> {
	const brief = buildReviewerBrief(scope);
	const dispatchResults = await Promise.allSettled(
		REVIEWERS.map((spec) => deps.dispatchReviewer(spec, brief).then((handle) => ({ spec, handle }))),
	);

	const dispatched: DispatchedReviewer[] = [];
	for (const [index, result] of dispatchResults.entries()) {
		const spec = REVIEWERS[index];
		if (!spec) continue;

		if (result.status === "rejected") {
			return {
				ok: false,
				failedReviewer: spec.agent,
				reason: `dispatch failed: ${errorMessage(result.reason)}`,
			};
		}

		dispatched.push(result.value);
	}

	const handles = dispatched.map((reviewer) => reviewer.handle);

	let waitResults: Map<string, ReviewerWaitResult>;
	try {
		waitResults = await deps.waitForReviewers(handles);
	} catch (error) {
		return {
			ok: false,
			failedReviewer: dispatched[0]!.spec.agent,
			reason: `wait failed: ${errorMessage(error)}`,
		};
	}

	const transposeResults = await Promise.allSettled(
		dispatched.map(async ({ spec, handle }) => {
			const wait = waitResults.get(handle) ?? { status: "unknown", result: null, error: null };
			if (wait.status !== "completed") {
				throw new ReviewerFailure(
					spec.agent,
					wait.status === "running" ? "reviewer running (timed out)" : `reviewer ${wait.status}`,
				);
			}

			const output = wait.result;
			if (output === null || output.trim() === "") {
				throw new ReviewerFailure(spec.agent, "reviewer returned no output");
			}

			const findings = await deps.transpose(output, spec.dimension);
			return { spec, findings };
		}),
	);

	const outcomes: { spec: ReviewerSpec; findings: Finding[] }[] = [];
	for (const [index, result] of transposeResults.entries()) {
		const dispatchedReviewer = dispatched[index];
		if (!dispatchedReviewer) continue;

		if (result.status === "fulfilled") {
			outcomes.push(result.value);
			continue;
		}

		const reason =
			result.reason instanceof ReviewerFailure
				? result.reason.reason
				: `transpose failed: ${errorMessage(result.reason)}`;
		return { ok: false, failedReviewer: dispatchedReviewer.spec.agent, reason };
	}

	const findings = mergeFindings(outcomes.map((outcome) => outcome.findings));
	const verdict = computeVerdict(findings);
	return {
		ok: true,
		result: {
			scope,
			verdict,
			findings,
			createdAt: (deps.now?.() ?? new Date()).toISOString(),
		},
	};
}
