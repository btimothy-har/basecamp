/**
 * Worker tool — registered as a pi tool the LLM calls to dispatch agents.
 *
 * Modes:
 *   { agent: "scout", task: "..." }              → pane (default)
 *   { agent: "scout", task: "...", mode: "background" } → headless
 *   { task: "Fix the bug" }                      → ad-hoc (no agent)
 *   { action: "list" }                           → list active workers
 */

import { randomUUID } from "node:crypto";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { AgentConfig } from "./types.ts";
import { WorkerToolParams, DEFAULT_WORKER_MAX_DEPTH } from "./types.ts";
import { spawnPane, spawnBackground } from "./spawner.ts";
import { addWorker, listWorkers } from "./worker-index.ts";

// ============================================================================
// Depth Guard
// ============================================================================

function checkDepth(): void {
  const depth = Number(process.env.BASECAMP_WORKER_DEPTH ?? "0");
  const max = Number(
    process.env.BASECAMP_WORKER_MAX_DEPTH ?? DEFAULT_WORKER_MAX_DEPTH,
  );
  if (depth >= max) {
    throw new Error(
      `Worker nesting blocked (depth=${depth}, max=${max}). ` +
        "Complete your task directly without spawning further workers.",
    );
  }
}

// ============================================================================
// Worker Environment
// ============================================================================

function buildWorkerEnv(opts: {
  name: string;
  parentSession: string;
  project: string;
}): Record<string, string> {
  const depth = Number(process.env.BASECAMP_WORKER_DEPTH ?? "0");

  // Forward all BASECAMP_* vars from parent, then override worker-specific ones
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (k.startsWith("BASECAMP_") && v !== undefined) {
      env[k] = v;
    }
  }

  env.BASECAMP_PROJECT = opts.project;
  env.BASECAMP_WORKER_NAME = opts.name;
  env.BASECAMP_PARENT_SESSION = opts.parentSession;
  env.BASECAMP_WORKER_DEPTH = String(depth + 1);
  env.BASECAMP_WORKER_MAX_DEPTH =
    process.env.BASECAMP_WORKER_MAX_DEPTH ?? String(DEFAULT_WORKER_MAX_DEPTH);

  return env;
}

// ============================================================================
// Tool Registration
// ============================================================================

export function registerWorkerTool(
  pi: ExtensionAPI,
  getAgents: () => AgentConfig[],
  getSessionName: () => string,
): void {
  pi.registerTool({
    name: "worker",
    label: "Worker",
    description: `Dispatch a worker agent or list active workers.

DISPATCH: { agent: "scout", task: "Investigate the auth module" }
BACKGROUND: { agent: "scout", task: "...", mode: "background" }
AD-HOC: { task: "Fix the login bug" }
LIST: { action: "list" }

Available agents are discovered from project (.basecamp/agents/), user (~/.basecamp/agents/), and builtin definitions.`,

    promptSnippet:
      "Dispatch a worker agent (Kitty pane or background) or list active workers",

    parameters: WorkerToolParams,

    async execute(_id, params, _signal, _onUpdate, ctx) {
      // --- List action ---
      if (params.action === "list") {
        const workers = listWorkers();
        if (workers.length === 0) {
          return {
            content: [{ type: "text", text: "No active workers." }],
          };
        }
        const lines = workers.map((w) => {
          const agentLabel = w.agent ?? "ad-hoc";
          const icon = w.mode === "pane" ? "🖥" : "⚙";
          const elapsed = Math.round((Date.now() - w.createdAt) / 1000);
          const age =
            elapsed < 60
              ? `${elapsed}s`
              : `${Math.round(elapsed / 60)}m`;
          return `${icon} ${w.name} [${w.status}] ${agentLabel} (${w.model}) ${age} ago`;
        });
        return {
          content: [{ type: "text", text: lines.join("\n") }],
        };
      }

      // --- Dispatch ---
      if (!params.task) {
        return {
          content: [
            { type: "text", text: "task is required for dispatching a worker" },
          ],
          isError: true,
        };
      }

      try {
        checkDepth();
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return { content: [{ type: "text", text: msg }], isError: true };
      }

      // Resolve agent config
      const agents = getAgents();
      let agentConfig: AgentConfig | null = null;
      if (params.agent) {
        agentConfig =
          agents.find((a) => a.name === params.agent) ?? null;
        if (!agentConfig) {
          const available =
            agents.map((a) => a.name).join(", ") || "none";
          return {
            content: [
              {
                type: "text",
                text: `Unknown agent: ${params.agent}. Available: ${available}`,
              },
            ],
            isError: true,
          };
        }
      }

      // Resolve parameters: explicit > agent default > fallback
      const mode = (params.mode ?? agentConfig?.mode ?? "pane") as
        | "pane"
        | "background";
      const model =
        params.model ?? agentConfig?.model ?? ctx.model?.id ?? "sonnet";
      const prefix = `worker-${randomUUID().slice(0, 6)}`;
      const name = params.name ? `${prefix}-${params.name}` : prefix;
      const project = process.env.BASECAMP_PROJECT ?? "default";
      const sessionDir = path.join(
        os.tmpdir(),
        "basecamp-workers",
        name,
        "session",
      );
      const parentSession = getSessionName();

      const env = buildWorkerEnv({ name, parentSession, project });

      try {
        if (mode === "pane") {
          await spawnPane(pi, agentConfig, params.task, {
            name,
            model,
            cwd: ctx.cwd,
            env,
            sessionDir,
          });

          addWorker({
            name,
            agent: params.agent ?? null,
            mode,
            status: "running",
            sessionDir,
            model,
            task: params.task,
            createdAt: Date.now(),
          });

          return {
            content: [
              {
                type: "text",
                text: `Worker **${name}** dispatched to Kitty pane (${model})`,
              },
            ],
          };
        }

        // Background mode
        const { pid, logPath } = spawnBackground(
          agentConfig,
          params.task,
          {
            name,
            model,
            cwd: ctx.cwd,
            env,
            sessionDir,
          },
        );

        addWorker({
          name,
          agent: params.agent ?? null,
          mode,
          status: "running",
          pid,
          sessionDir,
          model,
          task: params.task,
          createdAt: Date.now(),
        });

        return {
          content: [
            {
              type: "text",
              text: `Worker **${name}** started in background (pid ${pid})\nLog: ${logPath}`,
            },
          ],
        };
      } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        return { content: [{ type: "text", text: msg }], isError: true };
      }
    },
  });
}
