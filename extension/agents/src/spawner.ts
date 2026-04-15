/**
 * Worker spawning — synchronous subagent execution.
 *
 * Spawns `pi --mode json -p` as a child process, pipes stdout,
 * parses JSON events, and returns the subagent's final output
 * plus structured metadata (tool calls, usage) for rich rendering.
 *
 * Extensions load normally in workers. The basecamp prompt hook
 * sees --agent-prompt and slots the agent persona in place of
 * working style + system.md. Everything else (env block,
 * environment.md, tools, project context, git status) is
 * assembled by the same prompt.ts code path as the parent.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { AgentConfig, ToolCallRecord, UsageStats } from "./types.ts";

const WORKER_BASE = path.join(os.tmpdir(), "basecamp-workers");
const TASK_ARG_LIMIT = 8000;

// ============================================================================
// Result Types
// ============================================================================

export interface WorkerResult {
  exitCode: number;
  output: string;
  error?: string;
  model?: string;
  toolCalls: ToolCallRecord[];
  usage: UsageStats;
  durationMs: number;
}

// ============================================================================
// Pi CLI Argument Builder
// ============================================================================

interface PiArgsOpts {
  name: string;
  model: string | undefined;
  sessionDir: string;
  env: Record<string, string>;
}

function ensureWorkerDir(name: string): string {
  const dir = path.join(WORKER_BASE, name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function buildPiArgs(
  agent: AgentConfig | null,
  task: string,
  opts: PiArgsOpts,
): { args: string[]; workerDir: string } {
  const workerDir = ensureWorkerDir(opts.name);
  const args = ["pi", "--mode", "json", "-p"];

  if (opts.model) args.push("--model", opts.model);

  // Session directory for the worker's own session
  fs.mkdirSync(opts.sessionDir, { recursive: true });
  args.push("--session-dir", opts.sessionDir);

  // Extension sandboxing: only when agent explicitly declares an allowlist.
  // By default all extensions load (including basecamp, whose prompt hook
  // sees --agent-prompt and assembles the worker prompt variant).
  if (agent?.extensions !== undefined) {
    args.push("--no-extensions");
    for (const ext of agent.extensions) {
      args.push("--extension", ext);
    }
  }

  // Suppress skills and prompt templates — workers get focused instructions
  // from the agent persona, not ambient discovery
  args.push("--no-skills");
  args.push("--no-prompt-templates");

  // Agent prompt: written to a file, passed via --agent-prompt flag.
  // prompt.ts reads this and slots it in place of working style + system.md.
  if (agent?.systemPrompt) {
    const promptFile = path.join(workerDir, "prompt.md");
    fs.writeFileSync(promptFile, agent.systemPrompt, { mode: 0o600 });
    args.push("--agent-prompt", promptFile);
  }

  // Tool allowlist
  if (agent?.tools?.length) {
    args.push("--tools", agent.tools.join(","));
  }

  // Task — use a file for large tasks to avoid arg length limits
  const taskText = `Task: ${task}`;
  if (taskText.length > TASK_ARG_LIMIT) {
    const taskFile = path.join(workerDir, "task.md");
    fs.writeFileSync(taskFile, taskText, { mode: 0o600 });
    args.push(`@${taskFile}`);
  } else {
    args.push(taskText);
  }

  return { args, workerDir };
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

interface ParsedEvents {
  output: string;
  model?: string;
  error?: string;
  toolCalls: ToolCallRecord[];
  usage: UsageStats;
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
    input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0, turns: 0,
  };

  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const evt = JSON.parse(line) as {
        type?: string;
        toolName?: string;
        args?: unknown;
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

  return { output, model, error, toolCalls, usage };
}

// ============================================================================
// Synchronous Spawn
// ============================================================================

/**
 * Spawn a worker agent synchronously. Blocks until the subagent
 * completes and returns its output for the parent LLM to consume.
 */
export function spawnWorker(
  agent: AgentConfig | null,
  task: string,
  opts: {
    name: string;
    model: string | undefined;
    cwd: string;
    env: Record<string, string>;
    sessionDir: string;
  },
  signal?: AbortSignal,
): Promise<WorkerResult> {
  const { args } = buildPiArgs(agent, task, opts);
  const startTime = Date.now();

  return new Promise<WorkerResult>((resolve) => {
    const proc = spawn(args[0], args.slice(1), {
      cwd: opts.cwd,
      env: { ...process.env, ...opts.env },
      stdio: ["ignore", "pipe", "pipe"],
    });

    const stdoutLines: string[] = [];
    let stderrBuf = "";
    let stdoutBuf = "";
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
      });
    };

    proc.stdout.on("data", (chunk: Buffer) => {
      stdoutBuf += chunk.toString();
      const parts = stdoutBuf.split("\n");
      stdoutBuf = parts.pop() || "";
      stdoutLines.push(...parts);
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
        setTimeout(() => { if (!proc.killed) proc.kill("SIGKILL"); }, 3000);
      };
      if (signal.aborted) kill();
      else signal.addEventListener("abort", kill, { once: true });
    }
  });
}
