import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { deriveCurrentAgentHandle } from "pi-core/platform/agent-identity.ts";
import { getWorkspaceState, type WorkspaceState } from "pi-core/platform/workspace.ts";
import { buildWorkstreamLaunchBrief } from "./brief.ts";
import {
	findWorkstreamLaunchById,
	stampWorkstreamLaunchAgentHandle,
	type WorkstreamLaunchRecord,
	workstreamLaunchStatePath,
} from "./launch-state.ts";

export interface WorkstreamCommandDeps {
	getWorkspaceState(): WorkspaceState | null;
	launchStatePath(): string;
	findById(filePath: string, id: string, repo?: string): WorkstreamLaunchRecord | null;
	stampHandle(filePath: string, id: string, handle: string): WorkstreamLaunchRecord | null;
	deriveHandle(ctx: ExtensionContext): string | null;
}

export function defaultWorkstreamCommandDeps(): WorkstreamCommandDeps {
	return {
		getWorkspaceState,
		launchStatePath: workstreamLaunchStatePath,
		findById: findWorkstreamLaunchById,
		stampHandle: stampWorkstreamLaunchAgentHandle,
		deriveHandle: deriveCurrentAgentHandle,
	};
}

type WorkstreamHandleRegistration =
	| { status: "registered"; handle: string }
	| { status: "not_persisted"; handle: string }
	| { status: "unavailable" };

export function buildWorkstreamStartMessage(
	record: WorkstreamLaunchRecord,
	handleRegistration: WorkstreamHandleRegistration,
): string {
	const brief = buildWorkstreamLaunchBrief({
		source: record.source,
		workstream: {
			label: record.workstream.label,
			brief: record.workstream.brief,
			...(record.workstream.constraints ? { constraints: record.workstream.constraints } : {}),
		},
		worktree: {
			label: record.worktree.label,
			path: record.worktree.path ?? "",
			branch: record.worktree.branch ?? null,
		},
	});
	const handleNote =
		handleRegistration.status === "registered"
			? `\n\nThis workstream session is registered as \`${handleRegistration.handle}\`; copilot reaches it by that handle.`
			: handleRegistration.status === "not_persisted"
				? `\n\nNote: this session's agent handle was derived as \`${handleRegistration.handle}\`, but it could not be persisted to the launch record, so copilot may not be able to reach this workstream automatically.`
				: "\n\nNote: this session's agent handle could not be determined, so copilot may not be able to reach this workstream automatically.";
	return `${brief}${handleNote}`;
}

export function registerWorkstreamCommand(pi: ExtensionAPI, deps = defaultWorkstreamCommandDeps()): void {
	pi.registerCommand("workstream", {
		description: "Start a staged workstream by id: load its brief and register this session as its agent",
		handler: async (args, ctx) => {
			const id = args?.trim();
			if (!id) {
				ctx.ui.notify("Usage: /workstream <id> (get the id from copilot or list_workstream_launches).", "error");
				return;
			}

			const workspace = deps.getWorkspaceState();
			const repo = workspace?.repo?.isRepo ? workspace.repo.name : undefined;
			const statePath = deps.launchStatePath();
			const record = deps.findById(statePath, id, repo);
			if (!record) {
				ctx.ui.notify(
					`No staged workstream "${id}" found for this repository. Confirm the id with copilot (list_workstream_launches).`,
					"error",
				);
				return;
			}

			let handle: string | null = null;
			try {
				handle = deps.deriveHandle(ctx);
			} catch {
				handle = null;
			}
			let handleRegistration: WorkstreamHandleRegistration = { status: "unavailable" };
			if (handle) {
				try {
					const stamped = deps.stampHandle(statePath, record.id, handle);
					if (stamped) {
						handleRegistration = { status: "registered", handle };
					} else {
						handleRegistration = { status: "not_persisted", handle };
					}
				} catch {
					handleRegistration = { status: "not_persisted", handle };
				}
			}

			if (handleRegistration.status === "not_persisted") {
				ctx.ui.notify(
					`Derived agent handle "${handleRegistration.handle}" but could not persist it to the workstream record; copilot may not be able to reach this session automatically.`,
					"error",
				);
			}
			pi.sendUserMessage(buildWorkstreamStartMessage(record, handleRegistration));
		},
	});
}
