import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import {
	BASECAMP_RUN_ATTEMPT,
	BASECAMP_RUN_RESULT_PATH,
	BASECAMP_RUNNER_MANAGED_RESULT,
} from "../daemon/run-result.ts";

export function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

export async function waitForFrameCount(sent: Frame[], count: number): Promise<void> {
	for (let attempt = 0; attempt < 20; attempt++) {
		if (sent.length >= count) return;
		await new Promise((resolve) => setTimeout(resolve, 0));
	}
	assert.equal(sent.length, count);
}

export function telemetryFrames(sent: Frame[]): Array<Extract<Frame, { type: "telemetry" }>> {
	return sent.filter((frame): frame is Extract<Frame, { type: "telemetry" }> => frame.type === "telemetry");
}

const tempDirs: string[] = [];
const originalRunnerEnv = {
	[BASECAMP_RUNNER_MANAGED_RESULT]: process.env[BASECAMP_RUNNER_MANAGED_RESULT],
	[BASECAMP_RUN_RESULT_PATH]: process.env[BASECAMP_RUN_RESULT_PATH],
	[BASECAMP_RUN_ATTEMPT]: process.env[BASECAMP_RUN_ATTEMPT],
};

export async function tempRunResultPath(): Promise<string> {
	const directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), "basecamp-reporter-result-"));
	tempDirs.push(directory);
	return path.join(directory, "result.json");
}

function restoreEnv(name: string, value: string | undefined): void {
	if (value === undefined) delete process.env[name];
	else process.env[name] = value;
}

/**
 * Reproduces the shared per-test runner-env setup of the original
 * daemon-reporter suite. Call inside a describe block so the hooks scope
 * to that suite.
 */
export function installReporterEnvHooks(): void {
	beforeEach(() => {
		delete process.env[BASECAMP_RUNNER_MANAGED_RESULT];
		delete process.env[BASECAMP_RUN_RESULT_PATH];
		delete process.env[BASECAMP_RUN_ATTEMPT];
	});

	afterEach(async () => {
		restoreEnv(BASECAMP_RUNNER_MANAGED_RESULT, originalRunnerEnv[BASECAMP_RUNNER_MANAGED_RESULT]);
		restoreEnv(BASECAMP_RUN_RESULT_PATH, originalRunnerEnv[BASECAMP_RUN_RESULT_PATH]);
		restoreEnv(BASECAMP_RUN_ATTEMPT, originalRunnerEnv[BASECAMP_RUN_ATTEMPT]);
		await Promise.all(
			tempDirs.splice(0).map((directory) => fs.promises.rm(directory, { recursive: true, force: true })),
		);
	});
}
