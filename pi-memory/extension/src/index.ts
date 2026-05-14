import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

const SERVICE_NAME = "pi-memory";
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 8765;
const STATUS_TIMEOUT_MS = 500;
const READY_TIMEOUT_MS = 5_000;
const READY_POLL_INTERVAL_MS = 200;

export function statusUrl(host = DEFAULT_HOST, port = DEFAULT_PORT): string {
	return `http://${host}:${port}/v1/status`;
}

export async function isServiceHealthy(url = statusUrl(), timeoutMs = STATUS_TIMEOUT_MS): Promise<boolean> {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await fetch(url, {
			headers: { Accept: "application/json" },
			signal: controller.signal,
		});
		if (!response.ok) return false;

		const body = (await response.json()) as { service_name?: unknown };
		return body.service_name === SERVICE_NAME;
	} catch {
		return false;
	} finally {
		clearTimeout(timeout);
	}
}

function startService(onError: (error: Error) => void): void {
	const child = spawn(SERVICE_NAME, ["serve", "--host", DEFAULT_HOST, "--port", String(DEFAULT_PORT)], {
		detached: true,
		stdio: "ignore",
	});
	child.once("error", onError);
	child.unref();
}

async function waitUntilHealthy(): Promise<boolean> {
	const deadline = Date.now() + READY_TIMEOUT_MS;

	while (Date.now() < deadline) {
		if (await isServiceHealthy()) return true;
		await sleep(READY_POLL_INTERVAL_MS);
	}

	return isServiceHealthy();
}

async function ensureServiceRunning(ctx: ExtensionContext): Promise<void> {
	if (await isServiceHealthy()) return;

	const spawnFailure: { error: Error | null } = { error: null };
	try {
		startService((error) => {
			spawnFailure.error = error;
		});
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`${SERVICE_NAME}: failed to start local service — ${message}`, "warning");
		return;
	}

	if (!(await waitUntilHealthy())) {
		const suffix = spawnFailure.error ? ` — ${spawnFailure.error.message}` : ` at ${statusUrl()}`;
		ctx.ui.notify(`${SERVICE_NAME}: local service did not become healthy${suffix}`, "warning");
	}
}

export default function (pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		await ensureServiceRunning(ctx);
	});
}
