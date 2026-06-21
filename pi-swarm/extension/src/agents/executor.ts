/**
 * Shared subagent launch helpers.
 *
 * These helpers build the Pi CLI invocation used by daemon dispatch without
 * owning process execution.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { PiSwarmDependencies } from "../dependencies.ts";
import { buildSkillInjection, resolveSkills } from "./skills.ts";
import { type AgentConfig, getAgentRunKind, getAgentToolAllowlist } from "./types.ts";

const AGENT_BASE = path.join(os.tmpdir(), "basecamp-agents");
const TASK_ARG_LIMIT = 8000;
const VALID_THINKING_LEVELS = new Set(["off", "minimal", "low", "medium", "high", "xhigh"]);
const RESTRICTED_AGENT_REPORT_ENV_VARS = new Set([
	"BASECAMP_RUN_ID",
	"BASECAMP_REPORT_TOKEN",
	"BASECAMP_AGENT_ID",
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

function isPathWithin(parent: string, child: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
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

export interface PiArgsOpts {
	name: string;
	model: string | undefined;
	cwd: string;
	worktreeDir?: string | null;
	sessionDir: string;
	sessionId?: string;
	extensionTools: string[];
}

export function ensureAgentDir(name: string): string {
	const baseDir = path.resolve(AGENT_BASE);
	const dir = path.resolve(baseDir, name);
	if (!isPathWithin(baseDir, dir)) {
		throw new Error(`Agent directory is outside basecamp-agents directory: ${name}`);
	}
	fs.mkdirSync(dir, { recursive: true });
	return dir;
}

export interface PiAgentSkillDeps {
	readSkillContent: PiSwarmDependencies["readSkillContent"];
	buildSkillBlock: PiSwarmDependencies["buildSkillBlock"];
}

export function buildPiArgs(
	agent: AgentConfig | null,
	task: string,
	opts: PiArgsOpts,
	deps: PiAgentSkillDeps,
): { args: string[]; agentDir: string } {
	const agentDir = ensureAgentDir(opts.name);
	const args = ["pi", "--mode", "json", "-p"];

	if (opts.model) args.push("--model", opts.model);
	if (opts.worktreeDir) args.push("--worktree-dir", opts.worktreeDir);

	const thinkingLevel = normalizeThinkingLevel(agent?.thinking);
	if (thinkingLevel) args.push("--thinking", thinkingLevel);

	fs.mkdirSync(opts.sessionDir, { recursive: true });
	args.push("--session-dir", opts.sessionDir);
	if (opts.sessionId) args.push("--session-id", opts.sessionId);

	args.push("--no-prompt-templates");

	if (getAgentRunKind(agent) !== "mutative") args.push("--read-only");

	let skillInjection = "";
	if (agent?.skills?.length) {
		const { resolved } = resolveSkills(agent.skills, opts.cwd, deps);
		if (resolved.length > 0) {
			skillInjection = buildSkillInjection(resolved, deps);
		}
		args.push("--no-skills");
	}

	const effectivePrompt = agent?.systemPrompt
		? skillInjection
			? `${agent.systemPrompt}\n\n${skillInjection}`
			: agent.systemPrompt
		: skillInjection || null;

	if (effectivePrompt) {
		const promptFile = path.join(agentDir, "prompt.md");
		fs.writeFileSync(promptFile, effectivePrompt, { mode: 0o600 });
		args.push("--agent-prompt", promptFile);
	}

	const tools = [...new Set([...getAgentToolAllowlist(agent), ...opts.extensionTools])];
	args.push("--tools", tools.join(","));

	const taskText = `Task: ${task}`;
	if (taskText.length > TASK_ARG_LIMIT) {
		const taskFile = path.join(agentDir, "task.md");
		fs.writeFileSync(taskFile, taskText, { mode: 0o600 });
		args.push(`@${taskFile}`);
	} else {
		args.push(taskText);
	}

	return { args, agentDir };
}
