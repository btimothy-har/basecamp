import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	checkHerdrEligibility,
	type HerdrCommandResult,
	type HerdrEnv,
	type HerdrSkipReason,
	runHerdr,
} from "#core/ui/herdr-pane.ts";

export interface HerdrWorkstreamWorkspaceInput {
	protectedRoot?: string;
	repo?: {
		root?: string;
	};
	launchCwd?: string;
	hasUI?: boolean;
}

export interface HerdrWorkstreamWorktreeInput {
	path: string;
	label: string;
}

export type HerdrWorkstreamSkipReason = HerdrSkipReason | "missing-cwd";

export interface HerdrWorkstreamOpenArgsOpened {
	args: string[];
}

export interface HerdrWorkstreamOpenArgsSkipped {
	args: null;
	status: "skipped";
	reason: HerdrWorkstreamSkipReason;
	message: string;
}

export type HerdrWorkstreamOpenArgsResult = HerdrWorkstreamOpenArgsOpened | HerdrWorkstreamOpenArgsSkipped;

export type HerdrWorkstreamOpenResult =
	| {
			status: "opened";
			message: string;
			args: string[];
			stdout?: string;
			stderr?: string;
	  }
	| {
			status: "skipped";
			reason: HerdrWorkstreamSkipReason;
			message: string;
	  }
	| {
			status: "failed";
			message: string;
			error?: string;
			exitCode?: number;
			stdout?: string;
			stderr?: string;
			args?: string[];
	  };

export interface HerdrWorkstreamOpenEligibilityInput {
	env: HerdrEnv;
	hasUI?: boolean;
}

function skipped(reason: HerdrWorkstreamSkipReason, message: string): HerdrWorkstreamOpenArgsSkipped {
	return { args: null, status: "skipped", reason, message };
}

export function shouldOpenWorkstreamInHerdr(
	input: HerdrWorkstreamOpenEligibilityInput,
): HerdrWorkstreamOpenArgsSkipped | null {
	const ineligible = checkHerdrEligibility({ env: input.env, hasUI: input.hasUI, subject: "workstreams" });
	if (!ineligible) return null;
	return skipped(ineligible.reason, `Herdr workstream open skipped: ${ineligible.detail}`);
}

function workspaceCwd(workspace: HerdrWorkstreamWorkspaceInput): string | null {
	return workspace.protectedRoot ?? workspace.repo?.root ?? workspace.launchCwd ?? null;
}

export function buildHerdrWorkstreamOpenArgs(
	workspace: HerdrWorkstreamWorkspaceInput,
	worktree: HerdrWorkstreamWorktreeInput,
	env: HerdrEnv,
): HerdrWorkstreamOpenArgsResult {
	const skip = shouldOpenWorkstreamInHerdr({ env, hasUI: workspace.hasUI });
	if (skip) return skip;

	const args = ["worktree", "open"];
	if (env.HERDR_WORKSPACE_ID) {
		args.push("--workspace", env.HERDR_WORKSPACE_ID);
	} else {
		const cwd = workspaceCwd(workspace);
		if (!cwd) return skipped("missing-cwd", "Herdr workstream open skipped: missing workspace cwd.");
		args.push("--cwd", cwd);
	}
	args.push("--path", worktree.path, "--label", worktree.label, "--no-focus", "--json");
	return { args };
}

function mapHerdrCommandResult(result: HerdrCommandResult<null>, args: string[]): HerdrWorkstreamOpenResult {
	if (result.status === "ok") {
		return {
			status: "opened",
			message: "Herdr workstream opened.",
			args,
			stdout: result.stdout,
			stderr: result.stderr,
		};
	}
	return {
		status: "failed",
		message: result.message,
		args,
		error: result.error,
		exitCode: result.exitCode,
		stdout: result.stdout,
		stderr: result.stderr,
	};
}

export async function openWorkstreamInHerdr(
	pi: Pick<ExtensionAPI, "exec">,
	workspace: HerdrWorkstreamWorkspaceInput,
	worktree: HerdrWorkstreamWorktreeInput,
	env: HerdrEnv = process.env,
): Promise<HerdrWorkstreamOpenResult> {
	const built = buildHerdrWorkstreamOpenArgs(workspace, worktree, env);
	if (built.args === null) {
		return { status: "skipped", reason: built.reason, message: built.message };
	}

	const result = await runHerdr(pi, built.args, "workstream open", () => null);
	return mapHerdrCommandResult(result, built.args);
}
