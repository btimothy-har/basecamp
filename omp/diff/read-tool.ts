import { type ExtensionAPI, Text, type Theme } from "@oh-my-pi/pi-coding-agent";
import { type LoadDiff, loadDiff } from "./loader.ts";

const TOOL_DESCRIPTION =
	"Read this branch's diff: every committed change since the merge base of the default branch and HEAD, plus staged, unstaged, and untracked working-tree changes. " +
	"Pass repository-relative paths to narrow the diff; omit paths for the full patch. " +
	"Returns the unified patch, or an explicit notice when there are no changes.";

/** Model-facing payload of the read_diff tool. */
export interface ReadDiffInput {
	paths?: string[];
}

export interface ReadDiffDetails {
	repository: string;
	defaultBranch: string;
	baseRevision: string;
	headRevision: string;
	fileCount: number;
	empty: boolean;
	warnings: string[];
}

type ArkType = ExtensionAPI["arktype"];

/** Strict model-facing parameter schema: unknown fields are rejected. */
export function createReadDiffParameters(type: ArkType) {
	return type({
		"paths?": type("string > 0")
			.array()
			.describe("Repository-relative paths to limit the diff to; omit for the full diff."),
		"+": "reject",
	});
}

function renderReadDiffResult(details: ReadDiffDetails, theme: Theme): string {
	const title = details.empty ? "No changes" : "Branch diff";
	const files = `${details.fileCount} file${details.fileCount === 1 ? "" : "s"}`;
	return [
		theme.fg("toolTitle", theme.bold(title)),
		`${files} · base ${details.baseRevision.slice(0, 12)} · ${details.repository}`,
	].join("\n");
}

/**
 * Register the read_diff tool. Available in every agent mode: only /diff
 * itself is TUI-bound, and any agent may need to read the branch's changes.
 * The loader is injectable so tests never touch a real repository.
 */
export default function registerReadDiffTool(pi: ExtensionAPI, load: LoadDiff = loadDiff): void {
	const parameters = createReadDiffParameters(pi.arktype);
	pi.registerTool<typeof parameters, ReadDiffDetails>({
		name: "read_diff",
		label: "Read diff",
		description: TOOL_DESCRIPTION,
		parameters,
		approval: "read",
		strict: true,
		loadMode: "essential",
		async execute(_toolCallId, rawParams, signal, _onUpdate, ctx) {
			const params = rawParams as ReadDiffInput;
			const snapshot = await load(ctx.cwd, { paths: params.paths, signal });
			const warnings = snapshot.warnings ?? [];
			const details: ReadDiffDetails = {
				repository: snapshot.repository,
				defaultBranch: snapshot.defaultBranch,
				baseRevision: snapshot.baseRevision,
				headRevision: snapshot.headRevision,
				fileCount: snapshot.files.length,
				empty: snapshot.patch.length === 0,
				warnings,
			};
			const content = [
				{
					type: "text" as const,
					text: details.empty
						? `No changes: the diff from ${snapshot.baseRevision} (merge base of ${snapshot.defaultBranch} and HEAD) to the working tree is empty.`
						: snapshot.patch,
				},
			];
			if (warnings.length > 0) {
				content.push({ type: "text", text: `Diff warnings:\n- ${warnings.join("\n- ")}` });
			}
			return {
				content,
				details,
			};
		},
		renderCall(args, options, theme) {
			const count = Array.isArray(args.paths) ? args.paths.length : 0;
			const scope = count === 0 ? " full diff" : ` ${count} path${count === 1 ? "" : "s"}`;
			const suffix = options.isPartial ? "…" : scope;
			return new Text(`${theme.fg("toolTitle", theme.bold("read_diff"))}${theme.fg("muted", suffix)}`, 0, 0);
		},
		renderResult(result, _options, theme) {
			const fallback = result.content.find((part) => part.type === "text")?.text ?? "";
			return new Text(result.details ? renderReadDiffResult(result.details, theme) : fallback, 0, 0);
		},
	});
}
