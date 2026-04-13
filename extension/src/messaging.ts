import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs/promises";
import * as path from "node:path";

async function checkInbox(
  pi: ExtensionAPI,
  mode: "all" | "immediate",
): Promise<void> {
  const inboxDir = process.env.BASECAMP_INBOX_DIR;
  if (!inboxDir) return;

  let files: string[];
  try {
    const entries = await fs.readdir(inboxDir);
    if (mode === "immediate") {
      files = entries.filter(f => f.endsWith(".immediate")).sort();
    } else {
      files = entries.filter(f => f.endsWith(".msg") || f.endsWith(".immediate")).sort();
    }
  } catch {
    return; // Directory doesn't exist or isn't readable
  }

  if (files.length === 0) return;

  const messages: string[] = [];
  for (const file of files) {
    const filePath = path.join(inboxDir, file);
    try {
      const content = await fs.readFile(filePath, "utf8");
      await fs.unlink(filePath);
      if (content.trim()) messages.push(content.trim());
    } catch {
      // File disappeared between readdir and read — ignore
    }
  }

  if (messages.length === 0) return;

  const combined = messages.join("\n---\n");

  // Inject as a message the LLM will see
  pi.sendMessage({
    customType: "basecamp-inbox",
    content: `## Inbox Messages\n\n${combined}`,
    display: true,
  }, {
    deliverAs: mode === "immediate" ? "steer" : "followUp",
    triggerTurn: true,
  });
}

export function registerMessaging(pi: ExtensionAPI) {
  // Check for immediate messages after each tool execution
  pi.on("tool_execution_end", async (_event, _ctx) => {
    await checkInbox(pi, "immediate");
  });

  // Check all messages when agent finishes
  pi.on("agent_end", async (_event, _ctx) => {
    await checkInbox(pi, "all");
  });
}
