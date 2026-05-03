import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { exec } from "../../platform/exec.ts";
import { requireWorkspaceState } from "../../platform/workspace.ts";
import {
	formatRiskSummary,
	isHighRisk,
	isReadOnly,
	type ParsedGitCommand,
	parseGitCommand,
	type RiskClassification,
} from "./safe-git-policy.ts";

const OUTPUT_LIMIT = 16_000;
const AUDIT_OUTPUT_LIMIT = 1_000;
const EXEC_TIMEOUT_MS = 120_000;
const PREVIEW_TIMEOUT_MS = 10_000;

const SafeGitParams = Type.Object({
	command: Type.String({ description: "One single git command, e.g. `git push --force-with-lease origin branch`." }),
	reason: Type.String({ description: "Required justification to show the user before approval." }),
});

type SafeGitDecision = "rejected" | "declined" | "executed";

interface GitContext {
	repo: string;
	cwd: string;
	branch: string;
	defaultBranch: string;
	upstream: string | null;
	aheadBehind: string | null;
}

interface SafeGitDetails {
	decision: SafeGitDecision;
	normalizedCommand?: string;
	reason: string;
	risk?: RiskClassification;
	context?: GitContext;
	preview?: string[];
	exitCode?: number;
	stdout?: string;
	stderr?: string;
	message?: string;
}

interface ExecTextResult {
	code: number;
	stdout: string;
	stderr: string;
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function stripAnsi(value: string): string {
	let result = "";
	let index = 0;

	while (index < value.length) {
		if (value.charCodeAt(index) === 0x1b && value[index + 1] === "[") {
			index += 2;
			while (index < value.length) {
				const code = value.charCodeAt(index);
				index += 1;
				if (code >= 0x40 && code <= 0x7e) break;
			}
			continue;
		}

		result += value[index];
		index += 1;
	}

	return result;
}

function stripUnsafeControl(value: string): string {
	let result = "";
	for (const char of value) {
		const code = char.charCodeAt(0);
		if (code === 0x09 || code === 0x0a || code === 0x0d || (code >= 0x20 && code !== 0x7f)) result += char;
	}
	return result;
}

function sanitizeText(value: string, limit = OUTPUT_LIMIT): string {
	const sanitized = stripUnsafeControl(stripAnsi(value));
	return sanitized.length > limit ? `${sanitized.slice(0, limit)}\n... truncated ...` : sanitized;
}

function resultText(details: SafeGitDetails): string {
	const lines: string[] = [];
	if (details.decision === "executed") {
		lines.push(`safe_git executed: ${details.normalizedCommand}`, `Exit code: ${details.exitCode ?? "unknown"}`);
		if (details.stdout?.trim()) lines.push("", "stdout:", details.stdout.trimEnd());
		if (details.stderr?.trim()) lines.push("", "stderr:", details.stderr.trimEnd());
		return lines.join("\n");
	}

	lines.push(details.message ?? "safe_git did not execute the command.");
	if (details.normalizedCommand) lines.push(`Command: ${details.normalizedCommand}`);
	return lines.join("\n");
}

function toolResult(details: SafeGitDetails, isError = false) {
	return {
		isError,
		details,
		content: [{ type: "text" as const, text: resultText(details) }],
	};
}

function audit(pi: ExtensionAPI, details: SafeGitDetails): void {
	try {
		pi.appendEntry("safe-git", {
			decision: details.decision,
			normalizedCommand: details.normalizedCommand,
			reason: details.reason,
			risk: details.risk,
			context: details.context,
			preview: details.preview?.map((line) => sanitizeText(line, AUDIT_OUTPUT_LIMIT)),
			exitCode: details.exitCode,
			stdout: details.stdout ? sanitizeText(details.stdout, AUDIT_OUTPUT_LIMIT) : undefined,
			stderr: details.stderr ? sanitizeText(details.stderr, AUDIT_OUTPUT_LIMIT) : undefined,
			message: details.message,
		});
	} catch {
		/* audit is best-effort */
	}
}

async function git(pi: ExtensionAPI, args: string[], timeout = PREVIEW_TIMEOUT_MS): Promise<ExecTextResult> {
	const result = await exec(pi, "git", args, { timeout });
	return {
		code: result.code,
		stdout: sanitizeText(result.stdout),
		stderr: sanitizeText(result.stderr),
	};
}

async function gitOutput(pi: ExtensionAPI, args: string[]): Promise<string | null> {
	const result = await git(pi, args);
	if (result.code !== 0) return null;
	return result.stdout.trim() || null;
}

async function collectGitContext(pi: ExtensionAPI, cwd: string, repo: string): Promise<GitContext> {
	const [branch, originHead, upstream, aheadBehind] = await Promise.all([
		gitOutput(pi, ["branch", "--show-current"]),
		gitOutput(pi, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]),
		gitOutput(pi, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]),
		gitOutput(pi, ["rev-list", "--left-right", "--count", "@{u}...HEAD"]),
	]);

	return {
		repo,
		cwd,
		branch: branch || "detached HEAD",
		defaultBranch: originHead?.startsWith("origin/") ? originHead.slice("origin/".length) : "main",
		upstream,
		aheadBehind,
	};
}

function cleanPreviewArgs(command: ParsedGitCommand): string[] {
	const args: string[] = [];
	let hasDryRun = false;

	for (const arg of command.args) {
		if (arg === "--force") continue;
		if (arg === "-n" || arg === "--dry-run") hasDryRun = true;
		if (/^-[A-Za-z]+$/.test(arg) && arg.includes("f")) {
			const compact = arg.replaceAll("f", "");
			if (compact !== "-") args.push(compact);
			continue;
		}
		args.push(arg);
	}

	return ["clean", ...(hasDryRun ? [] : ["-n"]), ...args];
}

function formatAheadBehind(value: string | null): string | null {
	if (!value) return null;
	const [behindRaw, aheadRaw] = value.split(/\s+/);
	const behind = Number(behindRaw ?? 0);
	const ahead = Number(aheadRaw ?? 0);
	if (!Number.isFinite(ahead) || !Number.isFinite(behind)) return null;
	return `ahead ${ahead}, behind ${behind}`;
}

async function buildPreview(
	pi: ExtensionAPI,
	command: ParsedGitCommand,
	risk: RiskClassification,
	context: GitContext,
): Promise<string[]> {
	const preview: string[] = [];
	const aheadBehind = formatAheadBehind(context.aheadBehind);
	if (context.upstream) preview.push(`Upstream: ${context.upstream}${aheadBehind ? ` (${aheadBehind})` : ""}`);

	if (risk.category === "forced-clean") {
		const clean = await git(pi, cleanPreviewArgs(command));
		preview.push(
			clean.stdout.trim() ? `Clean preview:\n${clean.stdout.trimEnd()}` : "Clean preview: no untracked files matched.",
		);
		if (clean.stderr.trim()) preview.push(`Clean preview stderr:\n${clean.stderr.trimEnd()}`);
	}

	if (risk.requiresWorktree) {
		const status = await git(pi, ["status", "--short"]);
		preview.push(
			status.stdout.trim()
				? `Working tree before execution:\n${status.stdout.trimEnd()}`
				: "Working tree before execution: clean",
		);
	}

	return preview;
}

function riskDetails(risk: RiskClassification): string[] {
	if (!risk.details) return [];
	const lines: string[] = [];
	lines.push(`Operation: ${risk.details.operation}`);
	if (risk.details.target) lines.push(`Target: ${risk.details.target}`);
	if (risk.details.flags?.length) lines.push(`Flags: ${risk.details.flags.join(" ")}`);
	for (const note of risk.details.notes ?? []) lines.push(`Note: ${note}`);
	return lines;
}

function approvalPrompt(
	command: ParsedGitCommand,
	reason: string,
	risk: RiskClassification,
	context: GitContext,
	preview: string[],
): string {
	const lines = [
		`Command: ${command.normalizedCommand}`,
		`Reason: ${reason}`,
		`Repository: ${context.repo}`,
		`CWD: ${context.cwd}`,
		`Branch: ${context.branch}`,
		`Default branch: ${context.defaultBranch}`,
		`Risk: ${formatRiskSummary(risk)}`,
		...riskDetails(risk),
	];
	if (preview.length > 0) lines.push("", "Preview:", ...preview);
	return lines.map((line) => sanitizeText(line, 4_000)).join("\n");
}

function rejectionDetails(
	reason: string,
	commandReason: string,
	normalizedCommand?: string,
	risk?: RiskClassification,
): SafeGitDetails {
	return {
		decision: "rejected",
		normalizedCommand,
		reason: commandReason,
		risk,
		message: reason,
	};
}

function shouldBlockDefaultBranch(risk: RiskClassification, context: GitContext): boolean {
	return isHighRisk(risk) && context.branch === context.defaultBranch;
}

export function registerSafeGitTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "safe_git",
		label: "Safe Git",
		description:
			"Execute git commands through safe_git. Commands outside the approval blocklist execute automatically; " +
			"force-push, broad push, remote ref deletion, and forced clean require user approval. " +
			"The command is parsed into git argv and never run through a shell.",
		promptSnippet: "Execute git commands — non-blocklisted auto-executes, blocklisted requires approval",
		parameters: SafeGitParams,
		async execute(_id, params, signal, _onUpdate, ctx) {
			const rawReason = params.reason.trim();
			if (rawReason.length < 10) {
				const details = rejectionDetails("safe_git requires a specific reason of at least 10 characters.", rawReason);
				audit(pi, details);
				return toolResult(details, true);
			}

			const parsed = parseGitCommand(params.command);
			if (!parsed.ok) {
				const details = rejectionDetails(`safe_git rejected command: ${parsed.reason}`, rawReason);
				audit(pi, details);
				return toolResult(details, true);
			}

			const { risk } = parsed;
			const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;
			const isReadOnlyMode = pi.getFlag("read-only") === true;
			const hasUI = ctx.hasUI;

			const isRestrictedContext = isSubagent || isReadOnlyMode || !hasUI;
			if (isRestrictedContext) {
				if (!isReadOnly(risk) || risk.approvalRequired) {
					let reason: string;
					if (isSubagent) {
						reason = "Subagents can only execute read-only git commands (status, log, diff, etc.).";
					} else if (isReadOnlyMode) {
						reason = "Read-only mode: only read-only git commands (status, log, diff, etc.) are allowed.";
					} else {
						reason = "Non-interactive context: only read-only git commands (status, log, diff, etc.) are allowed.";
					}
					const details = rejectionDetails(reason, rawReason, parsed.command.normalizedCommand, risk);
					audit(pi, details);
					return toolResult(details, true);
				}
			}

			const workspace = requireWorkspaceState();
			if (workspace.repo === null) {
				const details = rejectionDetails(
					"safe_git requires a git repository session.",
					rawReason,
					parsed.command.normalizedCommand,
				);
				audit(pi, details);
				return toolResult(details, true);
			}

			const cwd = workspace.effectiveCwd;
			const activeWorktreePath = workspace.activeWorktree?.path ?? null;
			const protectedRoot = workspace.protectedRoot;
			const repoName = workspace.repo.name || path.basename(protectedRoot ?? cwd) || "unknown";

			if (risk.requiresWorktree) {
				if (!activeWorktreePath) {
					const details = rejectionDetails(
						"This git command can mutate repository state. Activate an execution worktree before using safe_git.",
						rawReason,
						parsed.command.normalizedCommand,
						risk,
					);
					audit(pi, details);
					return toolResult(details, true);
				}

				if (
					!isPathWithin(cwd, activeWorktreePath) ||
					(protectedRoot !== null && isPathWithin(cwd, protectedRoot))
				) {
					const details = rejectionDetails(
						`Mutating git commands must run inside the active worktree (${activeWorktreePath}), not ${cwd}.`,
						rawReason,
						parsed.command.normalizedCommand,
						risk,
					);
					audit(pi, details);
					return toolResult(details, true);
				}
			}

			if (!risk.approvalRequired) {
				const context = await collectGitContext(pi, cwd, repoName);

				const execution = await git(pi, parsed.command.argv.slice(1), EXEC_TIMEOUT_MS);
				const details: SafeGitDetails = {
					decision: "executed",
					normalizedCommand: parsed.command.normalizedCommand,
					reason: rawReason,
					risk,
					context,
					exitCode: execution.code,
					stdout: execution.stdout,
					stderr: execution.stderr,
				};
				audit(pi, details);
				return toolResult(details, execution.code !== 0);
			}

			const context = await collectGitContext(pi, cwd, repoName);
			const preview = await buildPreview(pi, parsed.command, risk, context);

			if (shouldBlockDefaultBranch(risk, context)) {
				const details: SafeGitDetails = {
					decision: "rejected",
					normalizedCommand: parsed.command.normalizedCommand,
					reason: rawReason,
					risk,
					context,
					preview,
					message: `safe_git rejected high-risk execution on the default branch (${context.defaultBranch}). Ask the user to run it manually if needed.`,
				};
				audit(pi, details);
				return toolResult(details, true);
			}

			const approved = await ctx.ui.confirm(
				"Approve safe_git execution?",
				approvalPrompt(parsed.command, rawReason, risk, context, preview),
				{ signal },
			);
			if (!approved) {
				const details: SafeGitDetails = {
					decision: "declined",
					normalizedCommand: parsed.command.normalizedCommand,
					reason: rawReason,
					risk,
					context,
					preview,
					message: "User declined safe_git execution; command was not run.",
				};
				audit(pi, details);
				return toolResult(details, true);
			}

			if (risk.typedConfirmationRequired) {
				const typed = (await ctx.ui.input("Type exact command to approve", ""))?.trim();
				if (typed !== parsed.command.normalizedCommand) {
					const details: SafeGitDetails = {
						decision: "declined",
						normalizedCommand: parsed.command.normalizedCommand,
						reason: rawReason,
						risk,
						context,
						preview,
						message: "Typed confirmation did not match; command was not run.",
					};
					audit(pi, details);
					return toolResult(details, true);
				}
			}

			const execution = await git(pi, parsed.command.argv.slice(1), EXEC_TIMEOUT_MS);
			const details: SafeGitDetails = {
				decision: "executed",
				normalizedCommand: parsed.command.normalizedCommand,
				reason: rawReason,
				risk,
				context,
				preview,
				exitCode: execution.code,
				stdout: execution.stdout,
				stderr: execution.stderr,
			};
			audit(pi, details);
			return toolResult(details, execution.code !== 0);
		},
	});
}
