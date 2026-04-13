import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs/promises";
import * as path from "node:path";

let gitRepo: string | undefined;

export default function (pi: ExtensionAPI) {
  // === session_start: set up git repo name and scratch directories ===
  pi.on("session_start", async (_event, ctx) => {
    try {
      const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd: ctx.cwd });
      gitRepo = path.basename(result.stdout.trim());
    } catch {
      gitRepo = path.basename(ctx.cwd);
    }
    process.env.GIT_REPO = gitRepo;

    const scratch = process.env.BASECAMP_SCRATCH_DIR || `/tmp/claude-workspace/${gitRepo}`;
    await fs.mkdir(path.join(scratch, "pull_requests"), { recursive: true });
    await fs.mkdir(path.join(scratch, "pr-comments"), { recursive: true });

    ctx.ui.notify(`pi-eng: repo=${gitRepo}, scratch=${scratch}`, "info");
  });

  // === tool_call: skill reminders on write/edit ===
  pi.on("tool_call", async (event, _ctx) => {
    if (event.toolName === "write" || event.toolName === "edit") {
      const filePath: string = event.input.path || "";
      if (filePath.endsWith(".py")) {
        pi.sendMessage(
          "Python file detected — consider loading /skill:python-development for best practices.",
          { deliverAs: "steer" }
        );
      } else if (filePath.endsWith(".sql")) {
        pi.sendMessage(
          "SQL file detected — consider loading /skill:sql for best practices.",
          { deliverAs: "steer" }
        );
      }
    }
  });

  // NOTE: allow-pr-comments.sh and allow-pr-push.sh cannot be directly ported.
  // Pi's tool_call event can only block ({ block: true, reason: "..." }), not
  // auto-allow. There is no permissionDecision: "allow" equivalent. Users should
  // configure their own bash permission preferences in settings.json or approve
  // gh commands when prompted.
}