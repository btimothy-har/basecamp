/**
 * Async agent spawning — detached process via jiti + async-runner.ts.
 *
 * Builds pi CLI args (reuses executor's buildPiArgs), writes a config file
 * to asyncDir, resolves jiti-cli.mjs, and spawns the runner script detached.
 * Returns immediately with the async ID and directory.
 */

import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { AgentConfig } from "./discovery.ts";
import { buildPiArgs, ensureAgentDir } from "./executor.ts";
import { buildSkillInjection, resolveSkills } from "./skills.ts";
import { type AsyncRunnerConfig, ASYNC_BASE_DIR, ASYNC_RESULTS_DIR } from "./types.ts";

const require = createRequire(import.meta.url);

// ============================================================================
// jiti Resolution
// ============================================================================

function resolveJitiCli(): string | undefined {
	const candidates: Array<() => string> = [
		() => path.join(path.dirname(require.resolve("jiti/package.json")), "lib/jiti-cli.mjs"),
		() => path.join(path.dirname(require.resolve("@mariozechner/jiti/package.json")), "lib/jiti-cli.mjs"),
		() => {
			const piEntry = fs.realpathSync(process.argv[1]!);
			const piRequire = createRequire(piEntry);
			return path.join(path.dirname(piRequire.resolve("@mariozechner/jiti/package.json")), "lib/jiti-cli.mjs");
		},
	];
	for (const candidate of candidates) {
		try {
			const p = candidate();
			if (fs.existsSync(p)) return p;
		} catch {
			// Candidate not available, try next.
		}
	}
	return undefined;
}

const jitiCliPath = resolveJitiCli();
const RUNNER_SCRIPT = path.join(path.dirname(fileURLToPath(import.meta.url)), "async-runner.ts");

// ============================================================================
// Public API
// ============================================================================

export function isAsyncAvailable(): boolean {
	return jitiCliPath !== undefined;
}

export interface AsyncSpawnOpts {
	name: string;
	model: string | undefined;
	cwd: string;
	env: Record<string, string>;
	sessionDir: string;
	extensionTools: string[];
	sessionId?: string;
}

export interface AsyncSpawnResult {
	asyncId: string;
	asyncDir: string;
	pid?: number;
	error?: string;
}

export function spawnAsyncAgent(
	agent: AgentConfig,
	task: string,
	opts: AsyncSpawnOpts,
): AsyncSpawnResult {
	if (!jitiCliPath) {
		return { asyncId: opts.name, asyncDir: "", error: "jiti not available — cannot spawn async runner" };
	}

	const asyncDir = path.join(ASYNC_BASE_DIR, opts.name);
	fs.mkdirSync(asyncDir, { recursive: true });

	// Build pi CLI args using the same logic as sync spawn
	const { args: piArgs } = buildPiArgs(agent, task, opts);

	// Write config for the runner script
	const config: AsyncRunnerConfig = {
		runId: opts.name,
		agent: agent.name,
		agentSource: agent.source,
		task,
		cwd: opts.cwd,
		model: opts.model,
		piArgs,
		asyncDir,
		resultsDir: ASYNC_RESULTS_DIR,
		sessionId: opts.sessionId,
	};

	const configPath = path.join(asyncDir, "config.json");
	fs.writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 });

	// Spawn the runner detached
	const proc = spawn(process.execPath, [jitiCliPath, RUNNER_SCRIPT, configPath], {
		cwd: opts.cwd,
		detached: true,
		stdio: "ignore",
		env: { ...process.env, ...opts.env },
		windowsHide: true,
	});

	proc.on("error", (err) => {
		console.error(`[async-spawn] Runner process error: ${err.message}`);
	});

	if (typeof proc.pid !== "number") {
		return { asyncId: opts.name, asyncDir, error: "Runner process did not start (no PID)" };
	}

	proc.unref();
	return { asyncId: opts.name, asyncDir, pid: proc.pid };
}
