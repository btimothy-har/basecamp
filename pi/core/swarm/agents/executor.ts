/**
 * Shared subagent launch helpers.
 *
 * These helpers build the Pi CLI invocation used by daemon dispatch without
 * owning process execution.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { isWithin } from "../../host/paths.ts";
import { type AgentConfig, getAgentToolAllowlist, getWorkspacelessAgentToolAllowlist } from "./types.ts";

const AGENT_BASE = path.join(os.tmpdir(), "basecamp-agents");
const TASK_ARG_LIMIT = 8000;
const VALID_THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh"]);
const RESTRICTED_AGENT_REPORT_ENV_VARS = new Set([
	"BASECAMP_RUN_ID",
	"BASECAMP_REPORT_TOKEN",
	"BASECAMP_AGENT_ID",
	"BASECAMP_AGENT_HANDLE",
	"BASECAMP_DAEMON_UDS",
]);

export function sanitizeAgentSpawnEnv(input: Record<string, string>): Record<string, string> {
	const output: Record<string, string> = {};
	for (const [key, value] of Object.entries(input)) {
		if (RESTRICTED_AGENT_REPORT_ENV_VARS.has(key)) continue;
		output[key] = value;
	}
	return output;
}

function hasControlCharacter(value: string): boolean {
	for (const char of value) {
		const code = char.charCodeAt(0);
		if (code <= 31 || (code >= 127 && code <= 159)) return true;
	}
	return false;
}

function normalizeThinkingLevel(value: string | undefined): string | undefined {
	if (!value) return undefined;
	const normalized = value.toLowerCase().trim();
	return VALID_THINKING_LEVELS.has(normalized) ? normalized : undefined;
}

function validateAgentRunSuffix(suffix: string): void {
	if (!suffix) {
		throw new Error("Invalid agent run-name suffix: suffix cannot be empty.");
	}
	if (hasControlCharacter(suffix) || suffix.includes("/") || suffix.includes("\\") || suffix.includes("..")) {
		throw new Error(`Invalid agent run-name suffix: "${suffix}"`);
	}
}

export function buildAgentRunName(prefix: string, suffix?: string): string {
	const normalizedPrefix = prefix.trim();
	if (!normalizedPrefix) {
		throw new Error("Invalid agent run-name prefix: missing base name.");
	}

	if (suffix === undefined) return normalizedPrefix;
	const normalizedSuffix = suffix.trim();
	validateAgentRunSuffix(normalizedSuffix);
	return `${normalizedPrefix}-${normalizedSuffix}`;
}

/**
 * The run's workspace posture, driving the contract layer of the agent prompt and the
 * toolset: a deliverable run works on its own branch, report/ask runs use branchless
 * detached scratch workspaces, and a non-repo run has no workspace — and therefore no
 * structured mutation tools (capability follows workspace).
 */
export type RunWorkspace = { kind: "deliverable"; branch: string } | { kind: "report" } | { kind: "ask" } | null;

export interface PiArgsOpts {
	name: string;
	model: string | undefined;
	sessionDir: string;
	sessionId?: string;
	extensionTools: string[];
	workspace: RunWorkspace;
}

export function ensureAgentDir(name: string): string {
	const baseDir = path.resolve(AGENT_BASE);
	const dir = path.resolve(baseDir, name);
	if (!isWithin(dir, baseDir)) {
		throw new Error(`Agent directory is outside basecamp-agents directory: ${name}`);
	}
	fs.mkdirSync(dir, { recursive: true });
	return dir;
}

function workspaceContract(workspace: RunWorkspace): string | null {
	if (!workspace) return null;
	if (workspace.kind === "ask") {
		return `## Workspace contract

You are answering a question from a detached snapshot workspace. It is discarded when this run ends — nothing you write here survives, so do not produce work products. Read whatever you need, then answer.`;
	}
	if (workspace.kind === "report") {
		return `## Workspace contract

You work in your own detached scratch workspace — a disposable copy of the parent's current state. It is discarded entirely when this run ends: **your report is your only deliverable**. Write freely for exploration (notes, experiments, builds); nothing here survives and commits are pointless. Never write outside your workspace.`;
	}
	return `## Workspace contract

You work in your own transient git workspace on branch \`${workspace.branch}\`. The workspace is discarded when this run ends — **only commits on your branch survive**.

- Commit deliverable work (\`git add\` + \`git commit\`) at logical checkpoints; the parent integrates your branch by merge.
- Do not commit scratch or exploration files — uncommitted state is discarded by design, so the tree is free scratch space.
- If you are re-tasked later you continue on this same branch: your earlier commits are already in your tree, or already merged into your base.
- Never write outside your workspace.`;
}

export function buildAgentTaskText(task: string): string {
	return `Task: ${task}

Completion contract:
- Always produce a final assistant response.
- Do not finish after only tool calls or task updates.
- If there are no findings, say that explicitly.
- If blocked, report the blocker explicitly.
- Before ending, ensure the final response is non-empty and directly answers the task.`;
}

export function buildPiArgs(
	agent: AgentConfig | null,
	task: string,
	opts: PiArgsOpts,
): { args: string[]; agentDir: string } {
	const agentDir = ensureAgentDir(opts.name);
	const args = ["pi", "--mode", "json", "-p"];

	if (opts.model) args.push("--model", opts.model);

	const thinkingLevel = normalizeThinkingLevel(agent?.thinking);
	if (thinkingLevel) args.push("--thinking", thinkingLevel);

	fs.mkdirSync(opts.sessionDir, { recursive: true });
	args.push("--session-dir", opts.sessionDir);
	if (opts.sessionId) args.push("--session-id", opts.sessionId);

	args.push("--no-prompt-templates");

	// A persona replaces the default prompt assembly, so its contract rides in the prompt
	// file. A persona-less run keeps the full default assembly (posture, working style) —
	// its contract rides in the task text instead of suppressing that assembly.
	const contract = workspaceContract(opts.workspace);
	if (agent?.systemPrompt) {
		const promptFile = path.join(agentDir, "prompt.md");
		fs.writeFileSync(promptFile, [agent.systemPrompt, contract].filter(Boolean).join("\n\n"), { mode: 0o600 });
		args.push("--agent-prompt", promptFile);
	}

	const baseTools = opts.workspace ? getAgentToolAllowlist() : getWorkspacelessAgentToolAllowlist();
	const tools = [...new Set([...baseTools, ...opts.extensionTools])];
	args.push("--tools", tools.join(","));

	const taskText =
		agent?.systemPrompt || !contract ? buildAgentTaskText(task) : `${contract}\n\n${buildAgentTaskText(task)}`;
	if (taskText.length > TASK_ARG_LIMIT) {
		const taskFile = path.join(agentDir, "task.md");
		fs.writeFileSync(taskFile, taskText, { mode: 0o600 });
		args.push(`@${taskFile}`);
	} else {
		args.push(taskText);
	}

	return { args, agentDir };
}
