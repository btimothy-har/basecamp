/**
 * The annotate_diff and remove_annotation tools. Registration captures `pi`
 * so executions append journal events with pi.appendEntry — the extension
 * context's session manager is read-only. Both tools are guarded to the
 * interactive TUI session, the only session that can run /diff and consume
 * what they record.
 */

import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import type { DiffAnnotation } from "./annotations.ts";
import { annotationId, span } from "./annotations.ts";
import type { AppendEntry } from "./journal.ts";
import { activeAnnotations, recordAnnotations, withdrawAnnotations } from "./journal.ts";
import { loadDiff } from "./loader.ts";
import type { AnnotationIssue } from "./validate.ts";
import { validateTargets } from "./validate.ts";

type ArkType = ExtensionAPI["arktype"];

export interface AnnotateDiffInput {
	annotations: {
		path: string;
		line_start: number;
		line_end: number;
		summary: string;
		rationale?: string;
	}[];
}

export interface RemoveAnnotationInput {
	ids: string[];
}

export interface AnnotateDiffDetails {
	recorded: DiffAnnotation[];
	skippedDuplicates: number;
	active: number;
	repository: string;
}

export interface RemoveAnnotationDetails {
	withdrawn: string[];
}

const ANNOTATE_DESCRIPTION = [
	"Annotate the current diff with notes that render inline beside the code the next time the user runs /diff.",
	"Annotate as you work — calls accumulate in the session journal until a completed /diff consumes them.",
	"Each annotation returns a stable id; when a later edit invalidates one (its anchored lines changed or moved), withdraw it with remove_annotation and annotate again.",
	"Paths are repository-relative; line_start and line_end are 1-based inclusive on the NEW side and must fall within one displayed diff hunk.",
	"Only the interactive session that can run /diff may annotate.",
].join(" ");

const REMOVE_DESCRIPTION = [
	"Withdraw annotations previously recorded with annotate_diff, before the next /diff consumes them.",
	"Use this when a later edit invalidated an annotation — the code it described moved or changed — or when you no longer stand behind it.",
	"Not for rewording: annotate again instead.",
	"Ids come from annotate_diff's confirmation; an id without an active annotation is an error (a completed /diff clears everything it showed).",
	"Only the interactive session that can run /diff may withdraw annotations.",
].join(" ");

export function createAnnotateDiffParameters(type: ArkType) {
	const annotation = type({
		path: type("string > 0").describe("Repository-relative path of the annotated file."),
		line_start: type("number.integer >= 1").describe("First line on the NEW side of the diff (1-based, inclusive)."),
		line_end: type("number.integer >= 1").describe(
			"Last line on the NEW side of the diff (1-based, inclusive); must be >= line_start.",
		),
		summary: type("string > 0").describe("One-sentence headline shown beside these lines in /diff."),
		"rationale?": type("string > 0").describe(
			"Why the note matters — intent, trade-off, follow-up. Omit when the summary says it all.",
		),
		"+": "reject",
	});
	return type({
		annotations: annotation
			.array()
			.atLeastLength(1)
			.describe(
				"Annotations to record. Each returns a stable id; exact duplicates of already-recorded annotations are skipped.",
			),
		"+": "reject",
	}).narrow((input, ctx) => {
		const reversed = input.annotations.find((item) => item.line_end < item.line_start);
		return (
			reversed === undefined ||
			ctx.mustBe(`annotation on ${JSON.stringify(reversed.path)} to use a line_end greater than or equal to line_start`)
		);
	});
}

export function createRemoveAnnotationParameters(type: ArkType) {
	return type({
		ids: type("string > 0").array().atLeastLength(1).describe("Annotation ids returned by annotate_diff."),
		"+": "reject",
	});
}

/** Only the interactive session can run /diff, so only it may mutate annotation state. */
function assertInteractive(ctx: ExtensionContext, tool: string): void {
	if (ctx.mode !== "tui" || !ctx.hasUI) {
		throw new Error(`${tool} is only available in the interactive session that owns /diff.`);
	}
}

function formatIssues(issues: readonly AnnotationIssue[]): string {
	const lines = issues.map((issue) => `- ${issue.path}${issue.range ? `:${span(issue.range)}` : ""} — ${issue.reason}`);
	return [`${issues.length} annotation target${issues.length === 1 ? "" : "s"} rejected:`, ...lines].join("\n");
}

/**
 * The ids must reach the model's context, not just the details payload —
 * remove_annotation is unusable unless the confirmation hands them back.
 */
function formatConfirmation(recorded: readonly DiffAnnotation[], skipped: number, active: number): string {
	if (recorded.length === 0) {
		const targets = skipped === 1 ? "the target was" : `all ${skipped} targets were`;
		return `No new annotations — ${targets} already recorded for the next /diff (${active} active).`;
	}
	const keys = recorded.map(
		(annotation) => `- ${annotation.id} ${annotation.path}:${span(annotation.newRange)} — ${annotation.summary}`,
	);
	return [
		`Recorded ${recorded.length} annotation${recorded.length === 1 ? "" : "s"} for the next /diff (${active} active total):`,
		...keys,
		"Withdraw one with remove_annotation if a later edit invalidates it.",
	].join("\n");
}

export interface AnnotationToolDeps {
	/** Test seam; production registrations use the real loader. */
	loadDiff?: typeof loadDiff;
}

export default function registerAnnotationTools(pi: ExtensionAPI, deps: AnnotationToolDeps = {}): void {
	const load = deps.loadDiff ?? loadDiff;
	const appendEntry: AppendEntry = (customType, data) => pi.appendEntry(customType, data);

	const annotateParameters = createAnnotateDiffParameters(pi.arktype);
	pi.registerTool<typeof annotateParameters, AnnotateDiffDetails>({
		name: "annotate_diff",
		label: "Annotate diff",
		description: ANNOTATE_DESCRIPTION,
		parameters: annotateParameters,
		approval: "write",
		strict: true,
		loadMode: "essential",
		async execute(_toolCallId, rawParams, signal, _onUpdate, ctx) {
			assertInteractive(ctx, "annotate_diff");
			const params = rawParams as unknown as AnnotateDiffInput;
			const snapshot = await load(ctx.cwd, { signal });
			const { valid, issues } = await validateTargets(
				snapshot,
				params.annotations.map((annotation) => ({
					path: annotation.path,
					range: { start: annotation.line_start, end: annotation.line_end },
					summary: annotation.summary,
					...(annotation.rationale === undefined ? {} : { rationale: annotation.rationale }),
				})),
			);
			if (issues.length > 0) throw new Error(formatIssues(issues));

			const active = activeAnnotations(ctx.sessionManager.getBranch());
			const activeIds = new Set(active.map((annotation) => annotation.id));
			const seen = new Set<string>();
			const recorded: DiffAnnotation[] = [];
			for (const target of valid) {
				const annotation: DiffAnnotation = {
					id: annotationId({
						repository: snapshot.repository,
						path: target.path,
						newRange: target.newRange,
						summary: target.summary,
						rationale: target.rationale,
					}),
					repository: snapshot.repository,
					path: target.path,
					newRange: target.newRange,
					anchorHash: target.anchorHash,
					summary: target.summary,
					...(target.rationale === undefined ? {} : { rationale: target.rationale }),
				};
				// Exact duplicates — same id, whether already journaled or repeated in
				// this batch — no-op; everything else is appended as one event.
				if (activeIds.has(annotation.id) || seen.has(annotation.id)) continue;
				seen.add(annotation.id);
				recorded.push(annotation);
			}
			recordAnnotations(appendEntry, recorded);
			const skipped = valid.length - recorded.length;
			return {
				content: [{ type: "text", text: formatConfirmation(recorded, skipped, activeIds.size + recorded.length) }],
				details: {
					recorded,
					skippedDuplicates: skipped,
					active: activeIds.size + recorded.length,
					repository: snapshot.repository,
				},
			};
		},
	});

	const removeParameters = createRemoveAnnotationParameters(pi.arktype);
	pi.registerTool<typeof removeParameters, RemoveAnnotationDetails>({
		name: "remove_annotation",
		label: "Remove annotation",
		description: REMOVE_DESCRIPTION,
		parameters: removeParameters,
		approval: "write",
		strict: true,
		loadMode: "essential",
		async execute(_toolCallId, rawParams, _signal, _onUpdate, ctx) {
			assertInteractive(ctx, "remove_annotation");
			const params = rawParams as unknown as RemoveAnnotationInput;
			const requested = [...new Set(params.ids)];
			const activeIds = new Set(activeAnnotations(ctx.sessionManager.getBranch()).map((annotation) => annotation.id));
			const unknown = requested.filter((id) => !activeIds.has(id));
			if (unknown.length > 0) {
				throw new Error(
					`No active annotation with id ${unknown.map((id) => JSON.stringify(id)).join(", ")} — already withdrawn or consumed by a completed /diff.`,
				);
			}
			withdrawAnnotations(appendEntry, requested);
			const count = requested.length;
			return {
				content: [
					{
						type: "text",
						text: `Withdrew ${count} annotation${count === 1 ? "" : "s"}; ${count === 1 ? "it" : "they"} will not appear in the next /diff.`,
					},
				],
				details: { withdrawn: requested },
			};
		},
	});
}
