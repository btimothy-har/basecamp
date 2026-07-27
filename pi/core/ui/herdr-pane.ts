/** Herdr CLI primitives: shared eligibility gating plus tab and pane control. */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "#core/errors.ts";

export const HERDR_COMMAND_TIMEOUT_MS = 5000;

export interface HerdrEnv {
	HERDR_ENV?: string;
	HERDR_SOCKET_PATH?: string;
	HERDR_PANE_ID?: string;
	HERDR_WORKSPACE_ID?: string;
	BASECAMP_AGENT_DEPTH?: string;
}

export type HerdrSkipReason =
	| "missing-herdr-env"
	| "missing-herdr-socket-path"
	| "missing-herdr-pane-id"
	| "subagent"
	| "headless";

export interface HerdrIneligible {
	reason: HerdrSkipReason;
	/** Sentence fragment; callers prefix it with their own subject so messages stay in their voice. */
	detail: string;
}

export interface HerdrEligibilityInput {
	env: HerdrEnv;
	hasUI?: boolean;
	/** What is being opened, e.g. "workstreams" — only used to phrase the subagent refusal. */
	subject: string;
}

function agentDepth(env: HerdrEnv): number {
	const raw = env.BASECAMP_AGENT_DEPTH;
	if (raw === undefined || raw.trim() === "") return 0;
	const parsed = Number(raw);
	// A malformed value is treated as a subagent: refusing a pane is safer than opening one blind.
	return Number.isFinite(parsed) ? parsed : 1;
}

export function checkHerdrEligibility(input: HerdrEligibilityInput): HerdrIneligible | null {
	if (input.env.HERDR_ENV !== "1") {
		return { reason: "missing-herdr-env", detail: "not running in Herdr." };
	}
	if (!input.env.HERDR_SOCKET_PATH) {
		return { reason: "missing-herdr-socket-path", detail: "missing Herdr socket path." };
	}
	if (!input.env.HERDR_PANE_ID) {
		return { reason: "missing-herdr-pane-id", detail: "missing Herdr pane id." };
	}
	if (agentDepth(input.env) !== 0) {
		return { reason: "subagent", detail: `only primary sessions can open ${input.subject} in Herdr.` };
	}
	if (input.hasUI === false) {
		return { reason: "headless", detail: "session has no UI." };
	}
	return null;
}

/**
 * `herdr pane run` types its argument list into the pane's shell without escaping anything, so an
 * unquoted `a;touch x` executes. Git refs legally contain `;`, `$`, `&`, and backticks, so every
 * element is single-quoted before it can reach a shell.
 */
export function shellQuote(arg: string): string {
	return `'${arg.replaceAll("'", "'\\''")}'`;
}

export type HerdrCommandResult<T> =
	| { status: "ok"; value: T; args: string[] }
	| {
			status: "failed";
			message: string;
			args: string[];
			error?: string;
			exitCode?: number;
			stdout?: string;
			stderr?: string;
	  };

export interface HerdrTabTarget {
	paneId: string;
	tabId: string;
}

export interface OpenHerdrTabInput {
	workspaceId: string;
	cwd: string;
	label: string;
	env?: Record<string, string>;
}

type HerdrExec = Pick<ExtensionAPI, "exec">;

async function runHerdr<T>(
	pi: HerdrExec,
	args: string[],
	what: string,
	parse: (stdout: string) => T,
): Promise<HerdrCommandResult<T>> {
	try {
		const result = await pi.exec("herdr", args, { timeout: HERDR_COMMAND_TIMEOUT_MS });
		if (result.code !== 0) {
			return {
				status: "failed",
				message: `Herdr ${what} failed with exit code ${result.code}.`,
				args,
				exitCode: result.code,
				stdout: result.stdout,
				stderr: result.stderr,
			};
		}
		return { status: "ok", value: parse(result.stdout), args };
	} catch (err) {
		return { status: "failed", message: `Herdr ${what} failed.`, args, error: errorMessage(err) };
	}
}

function parseTabTarget(stdout: string): HerdrTabTarget {
	const parsed: unknown = JSON.parse(stdout);
	const result = (parsed as { result?: unknown }).result as
		| { root_pane?: { pane_id?: unknown }; tab?: { tab_id?: unknown } }
		| undefined;
	const paneId = result?.root_pane?.pane_id;
	const tabId = result?.tab?.tab_id;
	if (typeof paneId !== "string" || typeof tabId !== "string") {
		throw new Error("Herdr tab create returned no pane id or tab id.");
	}
	return { paneId, tabId };
}

/**
 * Without an explicit --workspace the tab is created in whichever workspace currently has focus,
 * which is not necessarily this session's.
 */
export async function openHerdrTab(
	pi: HerdrExec,
	input: OpenHerdrTabInput,
): Promise<HerdrCommandResult<HerdrTabTarget>> {
	const args = [
		"tab",
		"create",
		"--workspace",
		input.workspaceId,
		"--cwd",
		input.cwd,
		"--label",
		input.label,
		"--no-focus",
	];
	for (const [key, value] of Object.entries(input.env ?? {})) {
		args.push("--env", `${key}=${value}`);
	}
	return await runHerdr(pi, args, "tab create", parseTabTarget);
}

export async function runInHerdrPane(pi: HerdrExec, paneId: string, argv: string[]): Promise<HerdrCommandResult<null>> {
	const args = ["pane", "run", paneId, ...argv.map(shellQuote)];
	return await runHerdr(pi, args, "pane run", () => null);
}

export async function closeHerdrTab(pi: HerdrExec, tabId: string): Promise<HerdrCommandResult<null>> {
	return await runHerdr(pi, ["tab", "close", tabId], "tab close", () => null);
}
