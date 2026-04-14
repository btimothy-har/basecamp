/**
 * Worker spawning — Kitty pane and background modes.
 *
 * Pane mode: spawns a visible Kitty window via remote control.
 * Background mode: spawns a headless `pi -p` process (detached).
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { AgentConfig } from "./types.ts";

const WORKER_BASE = path.join(os.tmpdir(), "basecamp-workers");
const TASK_ARG_LIMIT = 8000;

// ============================================================================
// Pi CLI Argument Builder
// ============================================================================

interface PiArgsOpts {
  name: string;
  model: string;
  sessionDir: string;
  printMode: boolean;
  env: Record<string, string>;
}

interface PiArgsResult {
  args: string[];
  workerDir: string;
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
): PiArgsResult {
  const workerDir = ensureWorkerDir(opts.name);
  const args = ["pi"];

  if (opts.printMode) args.push("-p");
  args.push("--model", opts.model);

  // Session directory for the worker's own session
  fs.mkdirSync(opts.sessionDir, { recursive: true });
  args.push("--session-dir", opts.sessionDir);

  // System prompt from agent definition
  if (agent?.systemPrompt) {
    const promptFile = path.join(workerDir, "prompt.md");
    fs.writeFileSync(promptFile, agent.systemPrompt, { mode: 0o600 });
    args.push("--append-system-prompt", promptFile);
  }

  // Tool allowlist
  if (agent?.tools?.length) {
    args.push("--tools", agent.tools.join(","));
  }

  // Extension sandboxing: absent = all, empty array = none, array = allowlist
  if (agent?.extensions !== undefined) {
    args.push("--no-extensions");
    for (const ext of agent.extensions) {
      args.push("--extension", ext);
    }
  }

  // Skill suppression (skills are injected into the system prompt body)
  if (agent?.skills?.length) {
    args.push("--no-skills");
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
// Launcher Script
// ============================================================================

function writeLauncherScript(workerDir: string, args: string[]): string {
  const launcherPath = path.join(workerDir, "launch.sh");
  // Quote each arg to handle spaces/special chars
  const quotedArgs = args.map((a) =>
    a.startsWith("@") ? a : `'${a.replace(/'/g, "'\\''")}'`,
  );
  fs.writeFileSync(launcherPath, `#!/bin/bash\nexec ${quotedArgs.join(" ")}\n`, {
    mode: 0o755,
  });
  return launcherPath;
}

// ============================================================================
// Pane Spawn (Kitty)
// ============================================================================

export async function spawnPane(
  pi: ExtensionAPI,
  agent: AgentConfig | null,
  task: string,
  opts: {
    name: string;
    model: string;
    cwd: string;
    env: Record<string, string>;
    sessionDir: string;
  },
): Promise<void> {
  const socket = process.env.KITTY_LISTEN_ON;
  if (!socket) {
    throw new Error(
      "Kitty not available — KITTY_LISTEN_ON not set. " +
        "Pane mode requires Kitty with allow_remote_control and listen_on configured.",
    );
  }

  const { args, workerDir } = buildPiArgs(agent, task, {
    ...opts,
    printMode: false,
  });
  const launcherPath = writeLauncherScript(workerDir, args);

  const kittyArgs = [
    "@",
    "--to",
    socket,
    "launch",
    "--type=window",
    "--keep-focus",
    "--copy-env",
    "--cwd",
    opts.cwd,
    "--title",
    opts.name,
  ];
  for (const [k, v] of Object.entries(opts.env)) {
    kittyArgs.push("--env", `${k}=${v}`);
  }
  kittyArgs.push(launcherPath);

  const result = await pi.exec("kitty", kittyArgs, { timeout: 10_000 });
  if (result.code !== 0) {
    throw new Error(`Kitty pane launch failed: ${result.stderr || "unknown error"}`);
  }
}

// ============================================================================
// Background Spawn
// ============================================================================

export function spawnBackground(
  agent: AgentConfig | null,
  task: string,
  opts: {
    name: string;
    model: string;
    cwd: string;
    env: Record<string, string>;
    sessionDir: string;
  },
): { pid: number; logPath: string } {
  const { args, workerDir } = buildPiArgs(agent, task, {
    ...opts,
    printMode: true,
  });

  const logPath = path.join(workerDir, "output.log");
  const logFd = fs.openSync(logPath, "w");

  const proc = spawn(args[0], args.slice(1), {
    cwd: opts.cwd,
    env: { ...process.env, ...opts.env },
    stdio: ["ignore", logFd, logFd],
    detached: true,
  });
  proc.unref();
  fs.closeSync(logFd);

  if (!proc.pid) {
    throw new Error("Failed to start background worker — no PID returned");
  }

  return { pid: proc.pid, logPath };
}
