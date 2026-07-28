import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { isSubagent } from "#core/host/env.ts";
import { removeAnnotation } from "./sidecar.ts";
import { reviewWorktreeDir } from "./worktree.ts";

export const RemoveAnnotationParams = Type.Object(
	{
		key: Type.String({ minLength: 1, description: "The annotation key returned by annotate_changeset." }),
	},
	{ additionalProperties: false },
);

const TOOL_DESCRIPTION = [
	"Withdraw an annotation previously recorded with annotate_changeset, before the next /diff consumes it.",
	"Use this when a later edit invalidated the annotation — the code it described moved or changed —",
	"or when you no longer stand behind it. Not for rewording: annotate again instead.",
	"Keys come from annotate_changeset's confirmation; an unknown key means the annotation is already gone",
	"(a completed /diff clears everything it showed).",
].join(" ");

export function registerRemoveTool(pi: ExtensionAPI): void {
	if (isSubagent()) return;

	pi.registerTool({
		name: "remove_annotation",
		label: "Remove annotation",
		description: TOOL_DESCRIPTION,
		parameters: RemoveAnnotationParams,
		async execute(_id, params) {
			const result = removeAnnotation(reviewWorktreeDir(), params.key);
			if (!result.removed) {
				throw new Error(result.reason);
			}
			return {
				content: [{ type: "text", text: `Withdrew annotation ${params.key}; it will not appear in the next /diff.` }],
				details: { key: params.key },
			};
		},
	});
}
