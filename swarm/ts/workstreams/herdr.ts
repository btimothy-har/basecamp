import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "../agents/errors.ts";

export const HERDR_WORKSTREAM_OPEN_TIMEOUT_MS = 5000;

export interface HerdrWorkstreamEnv {
	HERDR_ENV?: string;
	HERDR_SOCKET_PATH?: string;
	HERDR_PANE_ID?: string;
	HERDR_WORKSPACE_ID?: string;
	BASECAMP_AGENT_DEPTH?: string;
}

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

export type HerdrWorkstreamSkipReason =
	| "missing-herdr-env"
	| "missing-herdr-socket-path"
	| "missing-herdr-pane-id"
	| "subagent"
	| "headless"
	| "missing-cwd";

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

function agentDepth(env: HerdrWorkstreamEnv): number {
	const raw = env.BASECAMP_AGENT_DEPTH;
	if (raw === undefined || raw.trim() === "") return 0;
	const parsed = Number(raw);
	return Number.isFinite(parsed) ? parsed : 1;
}

export function shouldOpenWorkstreamInHerdr(
	input: HerdrWorkstreamOpenEligibilityInput,
): HerdrWorkstreamOpenArgsSkipped | null {
	if (input.env.HERDR_ENV !== "1")
		return skipped("missing-herdr-env", "Herdr workstream open skipped: not running in Herdr.");
	if (!input.env.HERDR_SOCKET_PATH) {
		return skipped("missing-herdr-socket-path", "Herdr workstream open skipped: missing Herdr socket path.");
	}
	if (!input.env.HERDR_PANE_ID) {
		return skipped("missing-herdr-pane-id", "Herdr workstream open skipped: missing Herdr pane id.");
	}
	if (agentDepth(input.env) !== 0) {
		return skipped("subagent", "Herdr workstream open skipped: only primary sessions can open workstreams in Herdr.");
	}
	if (input.hasUI === false) {
		return skipped("headless", "Herdr workstream open skipped: session has no UI.");
	}
	return null;
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
