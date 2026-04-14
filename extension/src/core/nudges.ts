import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const NUDGES: Record<string, string> = {
  ".py": "Python file detected — consider loading /skill:python-development for best practices.",
  ".sql": "SQL file detected — consider loading /skill:sql for best practices.",
};

export function registerNudges(pi: ExtensionAPI) {
  // Track which extensions have already been nudged this session
  // to avoid repeated noise
  const nudged = new Set<string>();

  pi.on("session_start", async () => {
    nudged.clear();
  });

  pi.on("tool_call", async (event, _ctx) => {
    if (event.toolName !== "write" && event.toolName !== "edit") return;

    const filePath: string = (event.input as { path?: string }).path || "";

    for (const [ext, message] of Object.entries(NUDGES)) {
      if (filePath.endsWith(ext) && !nudged.has(ext)) {
        nudged.add(ext);
        pi.sendMessage(message, { deliverAs: "steer" });
        break;
      }
    }
  });
}
