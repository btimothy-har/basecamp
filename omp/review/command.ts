import type { CustomCommand, CustomCommandAPI, HookCommandContext } from "@oh-my-pi/pi-coding-agent";
import { requireGit } from "@oh-my-pi/pi-natives/vcs";
import { buildReviewRequest, type ReviewScope } from "./request.ts";

const REVIEW_MODES = ["Against a base branch", "Specific commit", "Custom instructions"] as const;

function warn(ctx: HookCommandContext, message: string): void {
	ctx.ui.notify(message, "warning");
}

async function selectBranchScope(
	ctx: HookCommandContext,
	cwd: string,
	instructions: string | undefined,
): Promise<ReviewScope | undefined> {
	const repo = requireGit(cwd);
	const repositoryRoot = repo.info().repoRoot;
	const [currentBranch, branches] = await Promise.all([repo.currentBranch(), repo.listBranches(true)]);
	const baseBranches = branches.filter((branch) => branch !== currentBranch);
	if (baseBranches.length === 0) {
		warn(ctx, "No alternative base branches found.");
		return;
	}

	const headLabel = currentBranch ?? "HEAD";
	const baseBranch = await ctx.ui.select(
		`Select base branch for ${headLabel} in ${repositoryRoot}`,
		baseBranches,
	);
	if (!baseBranch) return;

	const [headRevision, baseRevision] = await Promise.all([
		repo.headSha(),
		repo.resolveRef(`${baseBranch}^{commit}`),
	]);
	if (!headRevision) throw new Error("HEAD did not resolve to a commit");
	if (!baseRevision) throw new Error(`Base branch ${baseBranch} did not resolve to a commit`);

	const mergeBase = await repo.mergeBase(baseRevision, headRevision);
	if (!mergeBase) throw new Error(`No common history between ${baseBranch} and ${headLabel}`);

	return {
		kind: "branch",
		repositoryRoot,
		baseBranch,
		headLabel,
		baseRevision: mergeBase,
		headRevision,
		...(instructions ? { instructions } : {}),
	};
}

async function selectCommitScope(
	ctx: HookCommandContext,
	cwd: string,
	instructions: string | undefined,
): Promise<ReviewScope | undefined> {
	const repo = requireGit(cwd);
	const repositoryRoot = repo.info().repoRoot;
	if (!(await repo.headSha())) {
		warn(ctx, "No commits found.");
		return;
	}
	const commits = await repo.logOnelines(20);
	if (commits.length === 0) {
		warn(ctx, "No commits found.");
		return;
	}

	const selected = await ctx.ui.select(`Select commit to review in ${repositoryRoot}`, commits);
	if (!selected) return;
	const [revision] = selected.trim().split(/\s+/, 1);
	if (!revision) throw new Error("Selected commit did not contain a revision");

	const commitRevision = await repo.resolveRef(`${revision}^{commit}`);
	if (!commitRevision) throw new Error(`Commit ${revision} did not resolve to a commit`);
	return {
		kind: "commit",
		repositoryRoot,
		commitRevision,
		...(instructions ? { instructions } : {}),
	};
}

async function selectInteractiveScope(
	ctx: HookCommandContext,
	cwd: string,
	initialInstructions: string,
): Promise<ReviewScope | undefined> {
	const mode = await ctx.ui.select(`Review scope for ${cwd}`, [...REVIEW_MODES]);
	if (!mode) return;

	if (mode === "Custom instructions") {
		const instructions = await ctx.ui.editor(
			"Custom review instructions",
			initialInstructions,
			undefined,
			{ promptStyle: true },
		);
		if (instructions === undefined || instructions.trim() === "") return;
		return { kind: "custom", cwd, instructions };
	}

	const instructions = initialInstructions || undefined;
	try {
		if (mode === "Against a base branch") return await selectBranchScope(ctx, cwd, instructions);
		return await selectCommitScope(ctx, cwd, instructions);
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`/review could not resolve the selected scope: ${message}`, "error");
		return;
	}
}

export default function createReviewCommand(_api: CustomCommandAPI): CustomCommand {
	return {
		name: "review",
		description: "Review a branch, commit, or custom scope (Basecamp)",
		execute: async (args, ctx) => {
			const cwd = ctx.cwd;
			const sessionId = ctx.sessionManager.getSessionId();
			if (!ctx.isIdle()) {
				warn(ctx, "Wait for the active turn to finish before starting /review.");
				return;
			}

			const initialInstructions = args.join(" ").trim();
			let scope: ReviewScope | undefined;
			if (ctx.hasUI) {
				scope = await selectInteractiveScope(ctx, cwd, initialInstructions);
			} else if (initialInstructions) {
				scope = { kind: "custom", cwd, instructions: initialInstructions };
			} else {
				warn(ctx, "/review requires custom instructions when no interactive UI is available.");
				return;
			}
			if (!scope) return;

			if (ctx.sessionManager.getCwd() !== cwd || ctx.sessionManager.getSessionId() !== sessionId) {
				warn(ctx, "/review stopped because the active session or workspace changed.");
				return;
			}
			return buildReviewRequest(scope);
		},
	};
}
