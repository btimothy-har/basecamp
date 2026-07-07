import type { Dimension, Finding } from "./findings.ts";
import { computeVerdict, mergeFindings, type Verdict } from "./synthesis.ts";

export interface ReviewScope {
	base: string;
	head: string;
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

export interface ReviewerOutcome {
	agent: string;
	dimension: Dimension;
	status: ReviewerStatus;
	prose: string | null;
	error: string | null;
	findings: Finding[];
	gap: string | null;
}

export interface ReviewResult {
	scope: ReviewScope;
	verdict: Verdict;
	findings: Finding[];
	reviewers: ReviewerOutcome[];
	createdAt: string;
}

export interface OrchestrateDeps {
	dispatchReviewer: (spec: ReviewerSpec, brief: string) => Promise<string>;
	waitForReviewers: (handles: string[]) => Promise<Map<string, ReviewerWaitResult>>;
	transpose: (prose: string, dimension: Dimension) => Promise<Finding[]>;
	now?: () => Date;
}

interface DispatchedReviewer {
	spec: ReviewerSpec;
	handle: string;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function reviewerGap(status: ReviewerStatus): string {
	if (status === "running") return "reviewer running (timed out)";
	return `reviewer ${status}`;
}

export function buildReviewerBrief(scope: ReviewScope): string {
	return `Review the code changes in the diff between ${scope.base} and ${scope.head} in the working directory ${scope.cwd}. Run git yourself to inspect the changes (e.g. git diff ${scope.base}...${scope.head}, git diff --stat, and read the changed files directly). Assess only what your specialist role covers. Report findings only — do not modify files or write fixes.`;
}

export async function runReview(scope: ReviewScope, deps: OrchestrateDeps): Promise<ReviewResult> {
	const brief = buildReviewerBrief(scope);
	const dispatchResults = await Promise.allSettled(
		REVIEWERS.map(async (spec) => ({ spec, handle: await deps.dispatchReviewer(spec, brief) })),
	);

	const dispatchedByAgent = new Map<string, DispatchedReviewer>();
	const outcomesByAgent = new Map<string, ReviewerOutcome>();

	for (const [index, dispatchResult] of dispatchResults.entries()) {
		const spec = REVIEWERS[index];
		if (!spec) continue;

		if (dispatchResult.status === "fulfilled") {
			dispatchedByAgent.set(spec.agent, dispatchResult.value);
			continue;
		}

		const message = errorMessage(dispatchResult.reason);
		outcomesByAgent.set(spec.agent, {
			agent: spec.agent,
			dimension: spec.dimension,
			status: "failed",
			prose: null,
			error: message,
			findings: [],
			gap: `dispatch failed: ${message}`,
		});
	}

	const dispatched = REVIEWERS.map((spec) => dispatchedByAgent.get(spec.agent)).filter(
		(reviewer): reviewer is DispatchedReviewer => reviewer !== undefined,
	);
	const handles = dispatched.map((reviewer) => reviewer.handle);

	let waitResults: Map<string, ReviewerWaitResult> | null = null;
	let waitError: string | null = null;
	if (handles.length > 0) {
		try {
			waitResults = await deps.waitForReviewers(handles);
		} catch (error) {
			waitError = errorMessage(error);
		}
	}

	const transposeResults = await Promise.allSettled(
		dispatched.map(async ({ spec, handle }): Promise<ReviewerOutcome> => {
			if (waitError !== null) {
				return {
					agent: spec.agent,
					dimension: spec.dimension,
					status: "unknown",
					prose: null,
					error: waitError,
					findings: [],
					gap: `wait failed: ${waitError}`,
				};
			}

			const waitResult = waitResults?.get(handle) ?? { status: "unknown", result: null, error: null };
			if (waitResult.status !== "completed") {
				return {
					agent: spec.agent,
					dimension: spec.dimension,
					status: waitResult.status,
					prose: waitResult.result,
					error: waitResult.error,
					findings: [],
					gap: reviewerGap(waitResult.status),
				};
			}

			const prose = waitResult.result;
			if (prose === null || prose.trim() === "") {
				return {
					agent: spec.agent,
					dimension: spec.dimension,
					status: "completed",
					prose,
					error: waitResult.error,
					findings: [],
					gap: "reviewer returned no output",
				};
			}

			try {
				return {
					agent: spec.agent,
					dimension: spec.dimension,
					status: "completed",
					prose,
					error: waitResult.error,
					findings: await deps.transpose(prose, spec.dimension),
					gap: null,
				};
			} catch (error) {
				const message = errorMessage(error);
				return {
					agent: spec.agent,
					dimension: spec.dimension,
					status: "completed",
					prose,
					error: message,
					findings: [],
					gap: `transpose failed: ${message}`,
				};
			}
		}),
	);

	for (const [index, transposeResult] of transposeResults.entries()) {
		const dispatchedReviewer = dispatched[index];
		if (!dispatchedReviewer) continue;

		if (transposeResult.status === "fulfilled") {
			outcomesByAgent.set(transposeResult.value.agent, transposeResult.value);
			continue;
		}

		const message = errorMessage(transposeResult.reason);
		outcomesByAgent.set(dispatchedReviewer.spec.agent, {
			agent: dispatchedReviewer.spec.agent,
			dimension: dispatchedReviewer.spec.dimension,
			status: "unknown",
			prose: null,
			error: message,
			findings: [],
			gap: `transpose failed: ${message}`,
		});
	}

	const reviewers = REVIEWERS.map((spec) => outcomesByAgent.get(spec.agent)).filter(
		(outcome): outcome is ReviewerOutcome => outcome !== undefined,
	);
	const findings = mergeFindings(reviewers.map((outcome) => outcome.findings));
	const verdict = computeVerdict(findings);

	return {
		scope,
		verdict,
		findings,
		reviewers,
		createdAt: (deps.now?.() ?? new Date()).toISOString(),
	};
}
