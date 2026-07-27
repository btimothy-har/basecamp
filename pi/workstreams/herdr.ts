import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";
import { checkHerdrEligibility, type HerdrEnv, type HerdrSkipReason } from "#core/ui/herdr-pane.ts";

export const HERDR_WORKSTREAM_OPEN_TIMEOUT_MS = 5000;

export type HerdrWorkstreamEnv = HerdrEnv;

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
	env: HerdrWorkstreamEnv;
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
	env: HerdrWorkstreamEnv,
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

export async function openWorkstreamInHerdr(
	pi: Pick<ExtensionAPI, "exec">,
	workspace: HerdrWorkstreamWorkspaceInput,
	worktree: HerdrWorkstreamWorktreeInput,
	env: HerdrWorkstreamEnv = process.env,
): Promise<HerdrWorkstreamOpenResult> {
	const built = buildHerdrWorkstreamOpenArgs(workspace, worktree, env);
	if (built.args === null) {
		return { status: "skipped", reason: built.reason, message: built.message };
	}

	try {
		const result = await pi.exec("herdr", built.args, { timeout: HERDR_WORKSTREAM_OPEN_TIMEOUT_MS });
		if (result.code !== 0) {
			return {
				status: "failed",
				message: `Herdr workstream open failed with exit code ${result.code}.`,
				exitCode: result.code,
				stdout: result.stdout,
				stderr: result.stderr,
				args: built.args,
			};
		}
		return {
			status: "opened",
			message: "Herdr workstream opened.",
			args: built.args,
			stdout: result.stdout,
			stderr: result.stderr,
		};
	} catch (err) {
		return {
			status: "failed",
			message: "Herdr workstream open failed.",
			error: errorMessage(err),
			args: built.args,
		};
	}
}
