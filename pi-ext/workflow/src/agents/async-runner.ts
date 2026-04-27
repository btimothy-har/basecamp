/**
 * Async agent runner — standalone script spawned detached by the parent.
 *
 * Reads config from a JSON file (passed as argv[2]), spawns `pi --mode json -p`,
 * parses JSON events from stdout, writes status.json periodically, and writes
 * result.json to the shared results directory on completion.
 *
 * Executed via jiti so TypeScript imports resolve at runtime.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import type { AsyncRunnerConfig, AsyncResult, AsyncStatus, UsageStats } from "./types.ts";

// ============================================================================
// JSON Event Parsing (adapted from executor.ts)
// ============================================================================

function extractTextFromContent(content: unknown): string {
	if (!Array.isArray(content)) return typeof content === "string" ? content : "";
	return content
		.filter((c: any) => c.type === "text" && typeof c.text === "string")
		.map((c: any) => c.text)
		.join("\n");
}

interface ParseState {
	output: string;
	model: string | undefined;
	error: string | undefined;
	toolCount: number;
	turnCount: number;
	usage: UsageStats;
}

function processLine(line: string, state: ParseState): void {
	if (!line.trim()) return;
	let evt: any;
	try {
		evt = JSON.parse(line);
	} catch {
		return;
	}

	if (evt.type === "tool_execution_start" && evt.toolName) {
		state.toolCount++;
	}

	if (evt.type === "message_end" && evt.message?.role === "assistant") {
		state.turnCount++;
		if (evt.message.model) state.model = evt.message.model;
		if (evt.message.errorMessage) state.error = evt.message.errorMessage;

		const text = extractTextFromContent(evt.message.content);
		if (text) state.output = text;

		const u = evt.message.usage;
		if (u) {
			state.usage.input += u.input ?? 0;
			state.usage.output += u.output ?? 0;
			state.usage.cacheRead += u.cacheRead ?? 0;
			state.usage.cacheWrite += u.cacheWrite ?? 0;
			state.usage.cost += u.cost?.total ?? 0;
		}
	}
}

// ============================================================================
// File I/O Helpers
// ============================================================================

function writeJsonAtomic(filePath: string, data: object): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmpPath = `${filePath}.${process.pid}.tmp`;
	try {
		fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), "utf-8");
		fs.renameSync(tmpPath, filePath);
	} finally {
		try {
			fs.unlinkSync(tmpPath);
		} catch {
			// Already renamed or cleaned up.
		}
	}
}

// ============================================================================
// Main
// ============================================================================

async function run(): Promise<void> {
	const configPath = process.argv[2];
	if (!configPath) {
		console.error("[async-runner] No config file argument provided");
		process.exit(1);
	}

	let config: AsyncRunnerConfig;
	try {
		config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
		fs.unlinkSync(configPath);
	} catch (err) {
		console.error("[async-runner] Failed to read config:", err);
		process.exit(1);
	}

	const { runId, agent, agentSource, task, cwd, piArgs, asyncDir, resultsDir, sessionId } = config;
	const statusPath = path.join(asyncDir, "status.json");
	const outputPath = path.join(asyncDir, "output.log");
	const resultPath = path.join(resultsDir, `${runId}.json`);

	fs.mkdirSync(asyncDir, { recursive: true });
	fs.mkdirSync(resultsDir, { recursive: true });

	const startedAt = Date.now();
	const state: ParseState = {
		output: "",
		model: config.model,
		error: undefined,
		toolCount: 0,
		turnCount: 0,
		usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0, turns: 0 },
	};

	const writeStatus = (overrides: Partial<AsyncStatus> = {}): void => {
		const status: AsyncStatus = {
			runId,
			agent,
			task,
			state: "running",
			startedAt,
			lastUpdate: Date.now(),
			pid: process.pid,
			cwd,
			model: state.model,
			toolCount: state.toolCount,
			turnCount: state.turnCount,
			usage: { ...state.usage, turns: state.turnCount },
			error: state.error,
			...overrides,
		};
		writeJsonAtomic(statusPath, status);
	};

	// Write initial status
	writeStatus();

	// Status update interval
	const statusInterval = setInterval(() => writeStatus(), 2000);
	statusInterval.unref?.();

	const outputStream = fs.createWriteStream(outputPath, { flags: "w" });

	const proc = spawn(piArgs[0]!, piArgs.slice(1), {
		cwd,
		env: process.env,
		stdio: ["ignore", "pipe", "pipe"],
	});

	let stdoutBuf = "";
	let stderrBuf = "";

	proc.stdout.on("data", (chunk: Buffer) => {
		const text = chunk.toString();
		outputStream.write(text);
		stdoutBuf += text;
		const lines = stdoutBuf.split("\n");
		stdoutBuf = lines.pop() || "";
		for (const line of lines) {
			processLine(line, state);
		}
	});

	proc.stderr.on("data", (chunk: Buffer) => {
		stderrBuf += chunk.toString();
	});

	const exitCode = await new Promise<number>((resolve) => {
		proc.on("close", (code) => resolve(code ?? 1));
		proc.on("error", (err) => {
			if (!state.error) state.error = err instanceof Error ? err.message : String(err);
			resolve(1);
		});
	});

	// Flush remaining buffer
	if (stdoutBuf.trim()) processLine(stdoutBuf, state);
	outputStream.end();

	clearInterval(statusInterval);

	const endedAt = Date.now();
	const success = exitCode === 0;

	if (!state.error && !success && stderrBuf.trim()) {
		state.error = stderrBuf.trim();
	}

	// Final status
	writeStatus({
		state: success ? "complete" : "failed",
		endedAt,
		error: state.error,
	});

	// Result file for the watcher to pick up
	const result: AsyncResult = {
		runId,
		agent,
		agentSource,
		task,
		success,
		output: state.output,
		error: state.error,
		model: state.model,
		usage: { ...state.usage, turns: state.turnCount },
		durationMs: endedAt - startedAt,
		cwd,
		sessionId,
	};
	writeJsonAtomic(resultPath, result);
}

run().catch((err) => {
	console.error("[async-runner] Fatal error:", err);
	process.exit(1);
});
