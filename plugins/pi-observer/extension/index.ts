import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

/**
 * Observer extension for pi.
 *
 * Hooks into session lifecycle events to trigger observer ingestion and
 * processing. Replaces the companion plugin's shell-script hooks.
 */
export default function (pi: ExtensionAPI) {
  // Helper: build hook input JSON and run observer ingest (detached).
  async function triggerIngest(ctx: { cwd: string; sessionManager: any }) {
    const sessionFile = ctx.sessionManager?.getSessionFile?.();
    const sessionId = ctx.sessionManager?.getSessionId?.();
    const cwd = ctx.cwd;

    if (!sessionFile || !sessionId) return;

    const hookInput = JSON.stringify({
      session_id: sessionId,
      transcript_path: sessionFile,
      cwd: cwd,
    });

    // Escape single quotes for shell embedding
    const escaped = hookInput.replace(/'/g, "'\\''");

    try {
      await pi.exec("bash", [
        "-c",
        `echo '${escaped}' | nohup observer ingest --process >/dev/null 2>&1 &`,
      ]);
    } catch {
      // Non-blocking — observer failures should never interrupt the session
    }
  }

  // --- Session lifecycle hooks ---

  pi.on("session_shutdown", async (_event, ctx) => {
    // Trigger observer ingest + process on session end.
    await triggerIngest(ctx);
  });

  pi.on("session_before_compact", async (_event, ctx) => {
    // Ingest before compaction discards context.
    await triggerIngest(ctx);
  });
}
