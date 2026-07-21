import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getWorkspaceState } from "./state.ts";

const GIT_STATUS_TIMEOUT_MS = 10_000;
const DIRTY_WORKTREE_REMINDER_TYPE = "basecamp-dirty-worktree-reminder";
const DIRTY_WORKTREE_REMINDER =
	"The active worktree still has uncommitted changes. Inspect them and commit only coherent changes related to the current task before settling. Do not stage or commit unrelated or pre-existing work. If the remaining changes are intentionally unfinished, leave them in place and explain why. Restate the substantive task result in your final response so this reminder does not replace the useful handoff.";

export interface DirtyWorktreeReminderOptions {
	getState?: typeof getWorkspaceState;
	isReadOnly?: () => boolean;
}

export function registerDirtyWorktreeReminder(pi: ExtensionAPI, options: DirtyWorktreeReminderOptions = {}): void {
	const getState = options.getState ?? getWorkspaceState;
	const isReadOnly = options.isReadOnly ?? (() => pi.getFlag("read-only") === true);
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
					content: DIRTY_WORKTREE_REMINDER,
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
