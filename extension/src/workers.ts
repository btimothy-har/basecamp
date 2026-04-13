import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export function registerWorkers(pi: ExtensionAPI) {
  pi.on("session_shutdown", async (_event, _ctx) => {
    const workerName = process.env.BASECAMP_WORKER_NAME;
    if (!workerName) return;

    try {
      await pi.exec("basecamp", ["worker", "close"], { timeout: 5_000 });
    } catch {
      // Best-effort — worker index update is non-critical
    }
  });
}
