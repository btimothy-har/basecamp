import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { type AnnotatedFile, writeSidecar } from "./sidecar.ts";

export const AnnotateChangesetParams = Type.Object(
	{
		summary: Type.String({ minLength: 1, description: "Top-level description of the whole changeset." }),
		files: Type.Array(
			Type.Object(
				{
					path: Type.String({ minLength: 1, description: "Path relative to the repo/worktree root." }),
					summary: Type.Optional(Type.String({ description: "Optional per-file summary." })),
					annotations: Type.Array(
						Type.Object(
							{
								newRange: Type.Tuple([
									Type.Integer({ description: "Start line, 1-based, on the NEW side of the diff." }),
									Type.Integer({ description: "End line, 1-based, on the NEW side of the diff." }),
								]),
								summary: Type.String({ minLength: 1, description: "Short headline for this annotation." }),
								rationale: Type.Optional(Type.String({ description: "Longer explanation; may contain newlines." })),
							},
							{ additionalProperties: false },
						),
					),
				},
				{ additionalProperties: false },
			),
		),
	},
	{ additionalProperties: false },
);
export type AnnotateChangesetParams = Static<typeof AnnotateChangesetParams>;

const TOOL_DESCRIPTION = [
	"Annotate the current changeset with rationale that renders inline beside the code in /diff.",
	"Call this once, when the work is complete — this version does not re-anchor line ranges against later edits,",
	"so annotating mid-task and then editing the same file above an annotated range will silently mis-anchor it.",
	"Paths are relative to the worktree root; newRange is [startLine, endLine] 1-based on the NEW side of the diff.",
	"Annotations on files not present in the changeset are silently dropped by the viewer.",
].join(" ");

const PROMPT_SNIPPET = "Annotate the changeset for /diff (call once, when work is complete)";

function formatConfirmation(result: { path: string; files: number; annotations: number }): string {
	return [
		`Recorded ${result.annotations} annotation${result.annotations === 1 ? "" : "s"} across ${result.files} file${result.files === 1 ? "" : "s"}.`,
		`Sidecar: ${result.path}`,
		"These will appear the next time you run /diff.",
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
			const worktreeDir = getBasecampEnv("BASECAMP_WORKTREE_DIR") ?? process.cwd();
			const files: AnnotatedFile[] = params.files;
			const result = writeSidecar(worktreeDir, params.summary, files);
			return {
				content: [{ type: "text", text: formatConfirmation(result) }],
				details: { sidecarPath: result.path, files: result.files, annotations: result.annotations },
			};
		},
	});
}
