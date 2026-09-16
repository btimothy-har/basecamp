/**
 * Herdr CLI adapter for transactional /diff: eligibility gating plus pane
 * split/run/close, and the `herdr:blocked` lifecycle that tells Herdr the
 * session is waiting on the user.
 *
 * `herdr pane run` types its argument list into the pane's shell without
 * escaping anything, so an unquoted `a;touch x` executes. Git refs legally
 * contain `;`, `$`, `&`, and backticks, so every element passed through it is
 * single-quoted before it can reach a shell.
 */

import { type } from "@oh-my-pi/omptype";
import type { ExecResult, ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

export const HERDR_COMMAND_TIMEOUT_MS = 5000;

type HerdrExec = Pick<ExtensionAPI, "exec">;

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

/** Single-quotes one argument for a POSIX shell, escaping embedded quotes. */
export function shellQuote(arg: string): string {
	return `'${arg.replaceAll("'", "'\\''")}'`;
}

export interface HerdrEnv {
	HERDR_ENV?: string;
	HERDR_SOCKET_PATH?: string;
	HERDR_PANE_ID?: string;
	HERDR_WORKSPACE_ID?: string;
}

export type HerdrSkipReason = "missing-herdr-env" | "missing-herdr-socket-path" | "missing-herdr-pane-id" | "headless";

export interface HerdrIneligible {
	reason: HerdrSkipReason;
	/** Sentence fragment; callers prefix it with their own subject so messages stay in their voice. */
	detail: string;
}

export interface HerdrEligibilityInput {
	env: HerdrEnv;
	hasUI?: boolean;
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
	if (input.hasUI === false) {
		return { reason: "headless", detail: "session has no UI." };
	}
	return null;
}

export type HerdrCommandResult<T> =
	| { status: "ok"; value: T; args: string[]; stdout?: string; stderr?: string }
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

export interface SplitHerdrPaneInput {
	/** The pane to split from (HERDR_PANE_ID). */
	paneId: string;
	cwd: string;
	env?: Record<string, string>;
	/** Default "right". */
	direction?: "right" | "down";
	/** Default 0.5. */
	ratio?: number;
}

export interface HerdrPaneProcess {
	pid: number;
	argv: string[];
}

/**
 * Runs `herdr <args>` and parses stdout. A parse failure is a failure, never a
 * zero value: a malformed pane id would silently retarget later pane commands.
 */
export async function runHerdr<T>(
	pi: HerdrExec,
	args: string[],
	what: string,
	parse: (stdout: string) => T,
	cwd?: string,
): Promise<HerdrCommandResult<T>> {
	let result: ExecResult;
	try {
		result = await pi.exec(
			"herdr",
			args,
			cwd ? { cwd, timeout: HERDR_COMMAND_TIMEOUT_MS } : { timeout: HERDR_COMMAND_TIMEOUT_MS },
		);
	} catch (err) {
		return { status: "failed", message: `Herdr ${what} failed.`, args, error: errorMessage(err) };
	}
	if (result.killed) {
		return {
			status: "failed",
			message: `Herdr ${what} was killed or timed out.`,
			args,
			exitCode: result.code,
			stdout: result.stdout,
			stderr: result.stderr,
		};
	}
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
	try {
		return { status: "ok", value: parse(result.stdout), args, stdout: result.stdout, stderr: result.stderr };
	} catch (err) {
		return { status: "failed", message: `Herdr ${what} returned unreadable output.`, args, error: errorMessage(err) };
	}
}

const PaneSplitResult = type({
	result: { pane: { pane_id: "string", tab_id: "string" } },
});

function parsePaneTarget(stdout: string): HerdrTabTarget {
	const parsed = PaneSplitResult(JSON.parse(stdout));
	if (parsed instanceof type.errors) {
		throw new Error("Herdr pane split returned no pane id or tab id.");
	}
	return { paneId: parsed.result.pane.pane_id, tabId: parsed.result.pane.tab_id };
}

const PaneProcessInfo = type({
	result: {
		process_info: {
			foreground_processes: type({
				pid: type("number.integer >= 1"),
				argv: type("string").array(),
			}).array(),
		},
	},
});

function parsePaneProcesses(stdout: string): HerdrPaneProcess[] {
	const parsed = PaneProcessInfo(JSON.parse(stdout));
	if (parsed instanceof type.errors) {
		throw new Error("Herdr pane process info returned no readable foreground processes.");
	}
	return parsed.result.process_info.foreground_processes;
}

/**
 * Splits the current session's pane rightward at 50% so hunk appears
 * side-by-side with the session. `pane split` has no `--label` flag, so the
 * new pane's terminal title comes from hunk.
 */
export async function splitHerdrPane(
	pi: HerdrExec,
	input: SplitHerdrPaneInput,
): Promise<HerdrCommandResult<HerdrTabTarget>> {
	const args = [
		"pane",
		"split",
		input.paneId,
		"--direction",
		input.direction ?? "right",
		"--ratio",
		String(input.ratio ?? 0.5),
		"--cwd",
		input.cwd,
		"--no-focus",
	];
	for (const [key, value] of Object.entries(input.env ?? {})) {
		args.push("--env", `${key}=${value}`);
	}
	return await runHerdr(pi, args, "pane split", parsePaneTarget, input.cwd);
}

/** Every argv element is shell-quoted; see the module docblock. */
export async function runInHerdrPane(
	pi: HerdrExec,
	paneId: string,
	argv: string[],
	cwd?: string,
): Promise<HerdrCommandResult<null>> {
	const args = ["pane", "run", paneId, ...argv.map(shellQuote)];
	return await runHerdr(pi, args, "pane run", () => null, cwd);
}

/** `pane close` on an already-gone pane returns `pane_not_found` (exit 1). */
export async function closeHerdrPane(pi: HerdrExec, paneId: string, cwd?: string): Promise<HerdrCommandResult<null>> {
	return await runHerdr(pi, ["pane", "close", paneId], "pane close", () => null, cwd);
}

/** Read the exact processes in one pane so Hunk discovery can bind to its PID. */
export async function readHerdrPaneProcesses(
	pi: HerdrExec,
	paneId: string,
	cwd?: string,
): Promise<HerdrCommandResult<HerdrPaneProcess[]>> {
	return await runHerdr(pi, ["pane", "process-info", "--pane", paneId], "pane process info", parsePaneProcesses, cwd);
}

/**
 * Brackets an operation that blocks on the user with `herdr:blocked` events,
 * so Herdr can idle the session instead of treating it as stuck. The unblock
 * is emitted even when the operation throws.
 */
export async function withHerdrBlocked<T>(
	pi: Pick<ExtensionAPI, "events">,
	label: string,
	operation: () => Promise<T>,
): Promise<T> {
	pi.events.emit("herdr:blocked", { active: true, label });
	try {
		return await operation();
	} finally {
		pi.events.emit("herdr:blocked", { active: false });
	}
}
