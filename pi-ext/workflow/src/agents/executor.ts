/**
 * Subagent execution — synchronous child process spawning.
 *
 * Spawns `pi --mode json -p` as a child process, pipes stdout,
 * parses JSON events, and returns the subagent's final output
 * plus structured metadata (tool calls, usage) for rich rendering.
 *
 * Extensions load normally in subagents. The basecamp prompt hook
 * sees --agent-prompt and slots the agent persona in place of
 * working style + system.md. Everything else (env block,
 * environment.md, tools, project context, git status) is
 * assembled by the same prompt.ts code path as the parent.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { getPiCommand } from "../../../platform/config.ts";
import type { TaskProgressSnapshot, TaskProgressStatus, TaskProgressTask } from "../tasks/render";
import { buildSkillInjection, resolveSkills } from "./skills.ts";
import type { AgentConfig, ToolCallRecord, UsageStats } from "./types.ts";

// ============================================================================
// Streaming Event Types
// ============================================================================

export type AgentStreamEvent =
	| { kind: "tool_start"; toolCall: ToolCallRecord }
	| { kind: "task_progress"; taskProgress: TaskProgressSnapshot }
	| { kind: "message"; text: string; model?: string }
	| { kind: "turn_end"; usage: Partial<UsageStats> };

const AGENT_BASE = path.join(os.tmpdir(), "basecamp-agents");
const TASK_ARG_LIMIT = 8000;

// ============================================================================
// Result Types
// ============================================================================

export interface SpawnResult {
	exitCode: number;
	output: string;
	error?: string;
	model?: string;
	toolCalls: ToolCallRecord[];
	usage: UsageStats;
	durationMs: number;
	taskProgress?: TaskProgressSnapshot;
}

// ============================================================================
// Pi CLI Argument Builder
// ============================================================================

export interface PiArgsOpts {
	name: string;
	model: string | undefined;
	cwd: string;
	sessionDir: string;
	env: Record<string, string>;
	extensionTools: string[];
}

export function ensureAgentDir(name: string): string {
	const dir = path.join(AGENT_BASE, name);
	fs.mkdirSync(dir, { recursive: true });
	return dir;
}

export function buildPiArgs(agent: AgentConfig | null, task: string, opts: PiArgsOpts): { args: string[]; agentDir: string } {
	const agentDir = ensureAgentDir(opts.name);
	const [piCmd, ...piPrefix] = getPiCommand();
	const args = [piCmd, ...piPrefix, "--mode", "json", "-p"];

	if (opts.model) args.push("--model", opts.model);

	// Session directory for the subagent's own session
	fs.mkdirSync(opts.sessionDir, { recursive: true });
	args.push("--session-dir", opts.sessionDir);

	// Suppress prompt templates — subagents get focused instructions
	// from the agent persona, not ambient discovery
	args.push("--no-prompt-templates");

	// Skills: if the agent declares specific skills, resolve them by name
	// via pi's loadSkills() API, inject their content into the system prompt,
	// and pass --no-skills to suppress pi's own discovery (avoiding doubles).
	// If no skills declared, subagents discover skills normally like the parent.
	let skillInjection = "";
	if (agent?.skills?.length) {
		const { resolved } = resolveSkills(agent.skills, opts.cwd);
		if (resolved.length > 0) {
			skillInjection = buildSkillInjection(resolved);
		}
		// Suppress pi's own discovery — skills are baked into the prompt
		args.push("--no-skills");
		// missing skills are silently ignored; the agent runs with what's available
	}

	// Agent prompt: written to a file, passed via --agent-prompt flag.
	// prompt.ts reads this and slots it in place of working style + system.md.
	// If skills were resolved, append them to the agent's system prompt.
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

	// Tool allowlist — agent frontmatter controls built-ins; basecamp extension
	// tools are added dynamically so Pi 0.68+ keeps workflow tools available.
	if (agent?.tools?.length) {
		const tools = [...new Set([...agent.tools, ...opts.extensionTools])];
		args.push("--tools", tools.join(","));
	}

	// Task — use a file for large tasks to avoid arg length limits
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

// ============================================================================
// JSON Event Parsing
// ============================================================================

function extractTextFromContent(content: unknown): string {
	if (!Array.isArray(content)) return typeof content === "string" ? content : "";
	return content
		.filter((c: any) => c.type === "text" && typeof c.text === "string")
		.map((c: any) => c.text)
		.join("\n");
}

function extractToolCallArgs(args: unknown): Record<string, unknown> {
	if (args && typeof args === "object" && !Array.isArray(args)) {
		return args as Record<string, unknown>;
	}
	return {};
}

const TASK_TOOL_NAMES = new Set([
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"get_task",
	"annotate_task",
	"delete_task",
]);

function isTaskProgressStatus(value: unknown): value is TaskProgressStatus {
	return value === "pending" || value === "active" || value === "completed" || value === "deleted";
}

function extractToolResultText(result: unknown): string {
	if (!result || typeof result !== "object") return "";
	const content = (result as { content?: unknown }).content;
	return extractTextFromContent(content);
}

function parseToolResultJson(result: unknown): Record<string, unknown> | null {
	const text = extractToolResultText(result);
	if (!text.trim()) return null;
	try {
		const parsed = JSON.parse(text);
		return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
	} catch {
		return null;
	}
}

function taskFromUnknown(value: unknown, index: number, previous?: TaskProgressTask): TaskProgressTask | null {
	if (!value || typeof value !== "object" || Array.isArray(value)) return null;
	const raw = value as Record<string, unknown>;
	const label = typeof raw.label === "string" ? raw.label : previous?.label;
	const status = isTaskProgressStatus(raw.status) ? raw.status : previous?.status;
	if (!label || !status) return null;
	return { index, label, status, notes: typeof raw.notes === "string" ? raw.notes : (previous?.notes ?? null) };
}

function previousTaskByIndex(snapshot: TaskProgressSnapshot | undefined, index: number): TaskProgressTask | undefined {
	return snapshot?.tasks.find((task, fallbackIndex) => (task.index ?? fallbackIndex) === index);
}

function tasksFromResultRecord(
	tasks: unknown,
	previous: TaskProgressSnapshot | undefined,
): TaskProgressTask[] | undefined {
	if (!tasks || typeof tasks !== "object" || Array.isArray(tasks)) return undefined;
	const entries = Object.entries(tasks as Record<string, unknown>)
		.map(([key, value]) => ({ index: Number(key), value }))
		.filter((entry) => Number.isInteger(entry.index) && entry.index >= 0)
		.sort((a, b) => a.index - b.index);
	const parsed: TaskProgressTask[] = [];
	for (const entry of entries) {
		const task = taskFromUnknown(entry.value, entry.index, previousTaskByIndex(previous, entry.index));
		if (task) parsed.push(task);
	}
	return parsed;
}

function tasksFromCreateArgs(
	args: Record<string, unknown>,
	previous: TaskProgressSnapshot | undefined,
): TaskProgressTask[] {
	const tasks = Array.isArray(args.tasks) ? args.tasks : [];
	return tasks
		.map((value, index) => {
			const previousTask = previousTaskByIndex(previous, index);
			if (!value || typeof value !== "object" || Array.isArray(value)) return previousTask;
			const label = (value as Record<string, unknown>).label;
			return typeof label === "string" ? { index, label, status: previousTask?.status ?? "pending" } : previousTask;
		})
		.filter((task): task is TaskProgressTask => Boolean(task));
}

function mergeTaskProgress(
	previous: TaskProgressSnapshot | undefined,
	toolName: string,
	args: Record<string, unknown>,
	result: unknown,
): TaskProgressSnapshot | undefined {
	if (!TASK_TOOL_NAMES.has(toolName)) return undefined;
	const parsed = parseToolResultJson(result);
	const next: TaskProgressSnapshot = {
		goal: (typeof parsed?.goal === "string" ? parsed.goal : undefined) ?? previous?.goal ?? null,
		tasks: previous?.tasks ? previous.tasks.map((task) => ({ ...task })) : [],
	};
	const resultTasks = tasksFromResultRecord(parsed?.tasks, previous);

	if (toolName === "update_goal") {
		next.goal =
			(typeof parsed?.goal === "string" ? parsed.goal : undefined) ??
			(typeof args.goal === "string" ? args.goal : null);
		next.tasks = resultTasks ?? [];
		return next;
	}

	if (toolName === "create_tasks") {
		const argTasks = tasksFromCreateArgs(args, previous);
		const statuses = new Map((resultTasks ?? []).map((task) => [task.index ?? 0, task.status]));
		next.tasks =
			argTasks.length > 0
				? argTasks.map((task) => ({ ...task, status: statuses.get(task.index ?? 0) ?? task.status }))
				: (resultTasks ?? []);
		return next;
	}

	if (resultTasks) {
		next.tasks = resultTasks;
		return next;
	}

	const index =
		typeof parsed?.index === "number" ? parsed.index : typeof args.task === "number" ? args.task : undefined;
	if (index === undefined) return previous;
	const label = typeof parsed?.label === "string" ? parsed.label : previousTaskByIndex(previous, index)?.label;
	const status = isTaskProgressStatus(parsed?.status)
		? parsed.status
		: toolName === "complete_task"
			? "completed"
			: toolName === "delete_task"
				? "deleted"
				: toolName === "start_task"
					? "active"
					: undefined;
	if (!label || !status) return previous;

	if (toolName === "start_task") {
		next.tasks = next.tasks.map((task) => (task.status === "active" ? { ...task, status: "pending" } : task));
	}

	const existing = next.tasks.findIndex((task, fallbackIndex) => (task.index ?? fallbackIndex) === index);
	const task = {
		index,
		label,
		status,
		notes: typeof parsed?.notes === "string" ? parsed.notes : (previousTaskByIndex(previous, index)?.notes ?? null),
	};
	if (existing >= 0) next.tasks[existing] = task;
	else next.tasks.push(task);
	next.tasks.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
	return next;
}

interface ParsedEvents {
	output: string;
	model?: string;
	error?: string;
	toolCalls: ToolCallRecord[];
	usage: UsageStats;
	taskProgress?: TaskProgressSnapshot;
}

/**
 * Parse a single JSON event line and invoke onEvent if relevant.
 * Returns true if the line was successfully parsed.
 */
function processEventLine(
	line: string,
	onEvent: ((event: AgentStreamEvent) => void) | undefined,
	currentTaskProgress: TaskProgressSnapshot | undefined,
): {
	toolCall?: ToolCallRecord;
	taskProgress?: TaskProgressSnapshot;
	messageEnd?: { text: string; model?: string; error?: string; usage: Partial<UsageStats> };
} | null {
	if (!line.trim()) return null;
	try {
		const evt = JSON.parse(line) as {
			type?: string;
			toolName?: string;
			args?: unknown;
			result?: unknown;
			isError?: boolean;
			message?: {
				role?: string;
				model?: string;
				errorMessage?: string;
				content?: unknown;
				usage?: {
					input?: number;
					output?: number;
					cacheRead?: number;
					cacheWrite?: number;
					cost?: { total?: number };
				};
			};
		};

		if (evt.type === "tool_execution_start" && evt.toolName) {
			const toolCall: ToolCallRecord = {
				name: evt.toolName,
				args: extractToolCallArgs(evt.args),
			};
			onEvent?.({ kind: "tool_start", toolCall });
			return { toolCall };
		}

		if (evt.type === "tool_execution_end" && evt.toolName && !evt.isError) {
			const taskProgress = mergeTaskProgress(
				currentTaskProgress,
				evt.toolName,
				extractToolCallArgs(evt.args),
				evt.result,
			);
			if (taskProgress) onEvent?.({ kind: "task_progress", taskProgress });
			return taskProgress ? { taskProgress } : null;
		}

		if (evt.type === "message_end" && evt.message?.role === "assistant") {
			const text = extractTextFromContent(evt.message.content);
			const model = evt.message.model;
			const error = evt.message.errorMessage;
			const u = evt.message.usage;
			const usage: Partial<UsageStats> = {
				input: u?.input ?? 0,
				output: u?.output ?? 0,
				cacheRead: u?.cacheRead ?? 0,
				cacheWrite: u?.cacheWrite ?? 0,
				cost: u?.cost?.total ?? 0,
			};

			if (text) onEvent?.({ kind: "message", text, model });
			onEvent?.({ kind: "turn_end", usage });

			return { messageEnd: { text, model, error, usage } };
		}
	} catch {
		// Non-JSON lines are expected; skip.
	}
	return null;
}

/**
 * Parse accumulated stdout lines (JSON events from `pi --mode json`)
 * and extract output, model, errors, tool calls, and usage stats.
 */
function parseJsonEvents(lines: string[]): ParsedEvents {
	let output = "";
	let model: string | undefined;
	let error: string | undefined;
	const toolCalls: ToolCallRecord[] = [];
	const usage: UsageStats = {
		input: 0,
		output: 0,
		cacheRead: 0,
		cacheWrite: 0,
		cost: 0,
		turns: 0,
	};
	let taskProgress: TaskProgressSnapshot | undefined;

	for (const line of lines) {
		if (!line.trim()) continue;
		try {
			const evt = JSON.parse(line) as {
				type?: string;
				toolName?: string;
				args?: unknown;
				result?: unknown;
				isError?: boolean;
				message?: {
					role?: string;
					model?: string;
					errorMessage?: string;
					content?: unknown;
					usage?: {
						input?: number;
						output?: number;
						cacheRead?: number;
						cacheWrite?: number;
						cost?: { total?: number };
					};
				};
			};

			if (evt.type === "tool_execution_start" && evt.toolName) {
				toolCalls.push({
					name: evt.toolName,
					args: extractToolCallArgs(evt.args),
				});
			}

			if (evt.type === "tool_execution_end" && evt.toolName && !evt.isError) {
				taskProgress =
					mergeTaskProgress(taskProgress, evt.toolName, extractToolCallArgs(evt.args), evt.result) ?? taskProgress;
			}

			if (evt.type === "message_end" && evt.message?.role === "assistant") {
				usage.turns++;
				if (evt.message.model) model = evt.message.model;
				if (evt.message.errorMessage) error = evt.message.errorMessage;
				const text = extractTextFromContent(evt.message.content);
				if (text) output = text; // last assistant message wins

				const u = evt.message.usage;
				if (u) {
					usage.input += u.input ?? 0;
					usage.output += u.output ?? 0;
					usage.cacheRead += u.cacheRead ?? 0;
					usage.cacheWrite += u.cacheWrite ?? 0;
					usage.cost += u.cost?.total ?? 0;
				}
			}
		} catch {
			// Non-JSON lines are expected; skip.
		}
	}

	return { output, model, error, toolCalls, usage, taskProgress };
}

// ============================================================================
// Synchronous Spawn
// ============================================================================

/**
 * Spawn a subagent synchronously. Blocks until it completes and
 * returns its output for the parent LLM to consume.
 */
export function spawnAgent(
	agent: AgentConfig | null,
	task: string,
	opts: {
		name: string;
		model: string | undefined;
		cwd: string;
		env: Record<string, string>;
		sessionDir: string;
		extensionTools: string[];
		onEvent?: (event: AgentStreamEvent) => void;
	},
	signal?: AbortSignal,
): Promise<SpawnResult> {
	const { args } = buildPiArgs(agent, task, opts);
	const startTime = Date.now();

	return new Promise<SpawnResult>((resolve) => {
		const proc = spawn(args[0]!, args.slice(1), {
			cwd: opts.cwd,
			env: { ...process.env, ...opts.env },
			stdio: ["ignore", "pipe", "pipe"] as const,
		});

		const stdoutLines: string[] = [];
		let stderrBuf = "";
		let stdoutBuf = "";
		let taskProgress: TaskProgressSnapshot | undefined;
		let settled = false;

		const finish = (exitCode: number) => {
			if (settled) return;
			settled = true;

			// Flush remaining buffer
			if (stdoutBuf.trim()) stdoutLines.push(stdoutBuf);

			const parsed = parseJsonEvents(stdoutLines);
			const durationMs = Date.now() - startTime;

			// Determine error: explicit from events, or stderr on non-zero exit
			let error = parsed.error;
			if (!error && exitCode !== 0 && stderrBuf.trim()) {
				error = stderrBuf.trim();
			}

			resolve({
				exitCode,
				output: parsed.output,
				error,
				model: parsed.model,
				toolCalls: parsed.toolCalls,
				usage: parsed.usage,
				durationMs,
				taskProgress: parsed.taskProgress,
			});
		};

		proc.stdout.on("data", (chunk: Buffer) => {
			stdoutBuf += chunk.toString();
			const parts = stdoutBuf.split("\n");
			stdoutBuf = parts.pop() || "";
			for (const part of parts) {
				stdoutLines.push(part);
				const processed = processEventLine(part, opts.onEvent, taskProgress);
				if (processed?.taskProgress) taskProgress = processed.taskProgress;
			}
		});

		proc.stderr.on("data", (chunk: Buffer) => {
			stderrBuf += chunk.toString();
		});

		proc.on("close", (code) => finish(code ?? 1));
		proc.on("error", (err) => {
			if (!settled) {
				resolve({
					exitCode: 1,
					output: "",
					error: err instanceof Error ? err.message : String(err),
					toolCalls: [],
					usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0, turns: 0 },
					durationMs: Date.now() - startTime,
				});
			}
		});

		// Handle abort signal
		if (signal) {
			const kill = () => {
				if (settled) return;
				proc.kill("SIGTERM");
				setTimeout(() => {
					if (!proc.killed) proc.kill("SIGKILL");
				}, 3000);
			};
			if (signal.aborted) kill();
			else signal.addEventListener("abort", kill, { once: true });
		}
	});
}
