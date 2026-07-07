import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { deriveCurrentAgentHandle } from "pi-core/platform/agent-identity.ts";
import { registerSessionProductRoleProvider } from "pi-core/platform/product-role.ts";
import {
	getWorkspaceService,
	getWorkspaceState,
	type RepoContext,
	type WorkspaceState,
} from "pi-core/platform/workspace.ts";
import { setAgentMode } from "pi-core/session/agent-mode.ts";
import { ensureCurrentSessionStateForEvent } from "pi-core/state/index.ts";
import { buildWorkstreamLaunchBrief } from "./brief.ts";
import {
	findWorkstreamLaunchById,
	stampWorkstreamLaunchAgentHandle,
	type WorkstreamLaunchRecord,
	workstreamLaunchStatePath,
} from "./launch-state.ts";

const WORKSPACE_START_WAIT_MS = 1000;

export interface WorkstreamStartDeps {
	getWorkspaceState(): WorkspaceState | null;
	waitForWorkspaceState(): Promise<WorkspaceState | null>;
	launchStatePath(): string;
	findById(filePath: string, id: string, repo?: string): WorkstreamLaunchRecord | null;
	stampHandle(filePath: string, id: string, handle: string): WorkstreamLaunchRecord | null;
	deriveHandle(ctx: ExtensionContext): string | null;
	enterExploreMode(event: SessionStartEvent, ctx: ExtensionContext): void;
}

function waitForWorkspaceState(timeoutMs = WORKSPACE_START_WAIT_MS): Promise<WorkspaceState | null> {
	const current = getWorkspaceState();
	if (current) return Promise.resolve(current);

	const service = getWorkspaceService();
	const onChange = service?.onChange?.bind(service);
	if (!onChange) return Promise.resolve(null);

	return new Promise((resolve) => {
		let unsubscribe: (() => void) | null = null;
		let timer: ReturnType<typeof setTimeout> | null = null;
		const finish = (state: WorkspaceState | null) => {
			if (unsubscribe) unsubscribe();
			if (timer) clearTimeout(timer);
			resolve(state);
		};
		timer = setTimeout(() => finish(getWorkspaceState()), timeoutMs);
		unsubscribe = onChange((state) => {
			if (state) finish(state);
		});
	});
}

export function defaultWorkstreamStartDeps(): WorkstreamStartDeps {
	return {
		getWorkspaceState,
		waitForWorkspaceState,
		launchStatePath: workstreamLaunchStatePath,
		findById: findWorkstreamLaunchById,
		stampHandle: stampWorkstreamLaunchAgentHandle,
		deriveHandle: deriveCurrentAgentHandle,
		enterExploreMode: (event, ctx) => {
			// Best-effort: mode setup must never block workstream startup (brief injection) when cross-extension
			// session state is not ready.
			try {
				ensureCurrentSessionStateForEvent(event, ctx);
				setAgentMode("planning");
			} catch (err) {
				ctx.ui.notify(`basecamp: could not enter Explore mode for workstream — ${errorMessage(err)}`, "warning");
			}
		},
	};
}

function errorMessage(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
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
			path: record.worktree.path ?? "not recorded in launch record; use this session's current worktree",
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

type RepoWorkspaceState = WorkspaceState & { repo: RepoContext };

async function resolveWorkspaceForWorkstreamStart(
	id: string,
	ctx: ExtensionContext,
	deps: WorkstreamStartDeps,
): Promise<RepoWorkspaceState | null> {
	let workspace = deps.getWorkspaceState();
	if (!workspace) workspace = await deps.waitForWorkspaceState();
	if (!workspace?.repo?.isRepo) {
		ctx.ui.notify(
			`Cannot start staged workstream "${id}" because this session is not in a repository workspace.`,
			"error",
		);
		return null;
	}
	return workspace as RepoWorkspaceState;
}

export async function startWorkstream(
	idInput: string | undefined,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	deps = defaultWorkstreamStartDeps(),
): Promise<void> {
	const id = idInput?.trim();
	if (!id) {
		ctx.ui.notify("Usage: pi --workstream <id> (get the id from copilot or list_workstream_launches).", "error");
		return;
	}

	let statePath: string;
	let record: WorkstreamLaunchRecord | null;
	try {
		const workspace = await resolveWorkspaceForWorkstreamStart(id, ctx, deps);
		if (!workspace) return;

		statePath = deps.launchStatePath();
		record = deps.findById(statePath, id, workspace.repo.name);
	} catch (err) {
		ctx.ui.notify(`Could not load staged workstream "${id}" for this repository: ${errorMessage(err)}`, "error");
		return;
	}
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
}

export function registerWorkstreamStartup(pi: ExtensionAPI, deps = defaultWorkstreamStartDeps()): void {
	pi.registerFlag("workstream", {
		description: "Start a staged workstream by id on session startup",
		type: "string",
	});

	registerSessionProductRoleProvider({
		resolveProductRole: () => {
			const id = pi.getFlag("workstream");
			return typeof id === "string" && id.trim() ? "workstream_agent" : null;
		},
	});

	pi.on("session_start", async (event, ctx) => {
		const id = pi.getFlag("workstream") as string | undefined;
		if (id === undefined) return;
		// Force Explore on every workstream session_start (including reload) so the session always begins from a
		// planning posture; the executor/supervisor mode set at plan approval only persists within a single process.
		if (id.trim()) deps.enterExploreMode(event, ctx);
		await startWorkstream(id, pi, ctx, deps);
	});
}
