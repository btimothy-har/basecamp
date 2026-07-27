import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import { errorMessage } from "#core/errors.ts";
import { resolveReviewBase } from "#core/git/repo.ts";
import { isSubagent } from "#core/host/env.ts";
import { type AnnotatedFile, type WriteResult, writeSidecar } from "./sidecar.ts";
import { reviewWorktreeDir } from "./worktree.ts";

/**
 * Lines are two named integers rather than a tuple: hunk rejects a sidecar
 * outright when a range is 0-based or reversed, and named bounds with a
 * minimum are both easier for a model to get right and portable across
 * providers that cannot express array-form tuple schemas.
 */
const AnnotationParam = Type.Object(
	{
		startLine: Type.Integer({ minimum: 1, description: "First line, 1-based, on the NEW side of the diff." }),
		endLine: Type.Integer({ minimum: 1, description: "Last line, 1-based; must not precede startLine." }),
		summary: Type.String({ minLength: 1, description: "Short headline for this annotation." }),
		rationale: Type.Optional(Type.String({ description: "Longer explanation; may contain newlines." })),
	},
	{ additionalProperties: false },
);

const AnnotatedFileParam = Type.Object(
	{
		path: Type.String({ minLength: 1, description: "Path relative to the repo or worktree root." }),
		summary: Type.Optional(Type.String({ description: "Optional per-file summary." })),
		annotations: Type.Array(AnnotationParam),
	},
	{ additionalProperties: false },
);

export const AnnotateChangesetParams = Type.Object(
	{
		summary: Type.String({ minLength: 1, description: "Top-level description of the whole changeset." }),
		files: Type.Array(AnnotatedFileParam),
	},
	{ additionalProperties: false },
);
export type AnnotateChangesetParams = Static<typeof AnnotateChangesetParams>;

const TOOL_DESCRIPTION = [
	"Annotate the current changeset with rationale that renders inline beside the code in /diff.",
	"Call this once, when the work is complete — this version does not re-anchor line ranges against later edits,",
	"so annotating mid-task and then editing the same file above an annotated range will silently mis-anchor it.",
	"Paths are relative to the worktree root; startLine and endLine are 1-based on the NEW side of the diff.",
	"Annotations on files not present in the changeset are silently dropped by the viewer.",
].join(" ");

const PROMPT_SNIPPET = "Annotate the changeset for /diff (call once, when work is complete)";

/** JSON Schema cannot express endLine >= startLine, so the pairing is checked here. */
function invertedRanges(params: AnnotateChangesetParams): string[] {
	const inverted: string[] = [];
	for (const file of params.files) {
		for (const annotation of file.annotations) {
			if (annotation.endLine < annotation.startLine) {
				inverted.push(`${file.path} ${annotation.startLine}-${annotation.endLine}`);
			}
		}
	}
	return inverted;
}

function toAnnotatedFiles(params: AnnotateChangesetParams): AnnotatedFile[] {
	return params.files.map((file) => ({
		path: file.path,
		...(file.summary === undefined ? {} : { summary: file.summary }),
		annotations: file.annotations.map((annotation) => ({
			newRange: [annotation.startLine, annotation.endLine] as [number, number],
			summary: annotation.summary,
			...(annotation.rationale === undefined ? {} : { rationale: annotation.rationale }),
		})),
	}));
}

function formatConfirmation(result: WriteResult): string {
	return [
		`Recorded ${result.annotations} annotation${result.annotations === 1 ? "" : "s"} across ${result.files} file${result.files === 1 ? "" : "s"}.`,
		"These will appear the next time you run /diff, until the reviewed base moves on.",
	].join("\n");
}

export function registerAnnotateTool(pi: ExtensionAPI): void {
	if (isSubagent()) return;

	pi.registerTool({
		name: "annotate_changeset",
		label: "Annotate changeset",
		description: TOOL_DESCRIPTION,
		promptSnippet: PROMPT_SNIPPET,
		parameters: AnnotateChangesetParams,
		async execute(_id, params) {
			const inverted = invertedRanges(params);
			if (inverted.length > 0) {
				// Writing these would make hunk refuse to start on every later /diff.
				throw new Error(`endLine must not precede startLine: ${inverted.join(", ")}`);
			}
			const worktreeDir = reviewWorktreeDir();
			// Stamped so /diff can tell rationale about this changeset from rationale
			// left behind by whatever this worktree directory held previously.
			let base: string;
			try {
				base = await resolveReviewBase(pi, worktreeDir);
			} catch (err) {
				throw new Error(`Cannot anchor annotations: ${errorMessage(err)}`);
			}
			const result = writeSidecar(worktreeDir, base, params.summary, toAnnotatedFiles(params));
			return {
				content: [{ type: "text", text: formatConfirmation(result) }],
				details: { sidecarPath: result.path, files: result.files, annotations: result.annotations },
			};
		},
	});
}
