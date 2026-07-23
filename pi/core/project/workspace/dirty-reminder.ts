import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getAgentDepth } from "../../host/env.ts";
import { getWorkspaceState } from "./state.ts";

const GIT_STATUS_TIMEOUT_MS = 10_000;
const DIRTY_WORKTREE_REMINDER_TYPE = "basecamp-dirty-worktree-reminder";
const DIRTY_WORKTREE_REMINDER =
	"The active worktree still has uncommitted changes. Inspect them and commit only coherent changes related to the current task before settling. Do not stage or commit unrelated or pre-existing work. If the remaining changes are intentionally unfinished, leave them in place and explain why. Restate the substantive task result in your final response so this reminder does not replace the useful handoff.";
// Dispatched agents work in transient workspaces: uncommitted state is discarded at
// teardown by design, so the reminder distinguishes deliverables from scratch.
const AGENT_DIRTY_WORKTREE_REMINDER =
	"Your workspace has uncommitted changes and is discarded at teardown — only commits on your branch survive. If these changes are part of your deliverable, commit them now (git add + git commit). If they are scratch or exploration files, leave them; they vanish by design. Restate your substantive result in your final response.";

export interface DirtyWorktreeReminderOptions {
	getState?: typeof getWorkspaceState;
	isReadOnly?: () => boolean;
	isSubagent?: () => boolean;
}

export function registerDirtyWorktreeReminder(pi: ExtensionAPI, options: DirtyWorktreeReminderOptions = {}): void {
	const getState = options.getState ?? getWorkspaceState;
	const isReadOnly = options.isReadOnly ?? (() => pi.getFlag("read-only") === true);
	const isSubagent = options.isSubagent ?? (() => getAgentDepth() > 0);
	let reminderQueued = false;
	let reminderTurnActive = false;

	pi.on("message_start", (event) => {
		if (event.message.role !== "custom" || event.message.customType !== DIRTY_WORKTREE_REMINDER_TYPE) return;
		reminderQueued = false;
		reminderTurnActive = true;
	});

	// Queuing at agent_end keeps print-mode reminders inside the original prompt lifecycle.
	pi.on("agent_end", async () => {
		if (reminderQueued || reminderTurnActive) return;
		if (isReadOnly()) return;

		const worktreeDir = getState()?.activeWorktree?.path;
		if (!worktreeDir) return;

		try {
			const status = await pi.exec("git", ["-C", worktreeDir, "status", "--porcelain"], {
				timeout: GIT_STATUS_TIMEOUT_MS,
			});
			if (status.code !== 0 || status.killed === true || !status.stdout.trim()) return;

			reminderQueued = true;
			pi.sendMessage(
				{
					customType: DIRTY_WORKTREE_REMINDER_TYPE,
					content: isSubagent() ? AGENT_DIRTY_WORKTREE_REMINDER : DIRTY_WORKTREE_REMINDER,
					display: false,
				},
				{ deliverAs: "followUp" },
			);
		} catch {
			reminderQueued = false;
		}
	});

	pi.on("agent_settled", () => {
		reminderQueued = false;
		reminderTurnActive = false;
	});
}
