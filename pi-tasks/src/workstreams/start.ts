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
	findWorkstreamLaunchByWorktreeLabel,
	stampWorkstreamLaunchAgentHandle,
	type WorkstreamLaunchRecord,
	workstreamLaunchStatePath,
} from "./launch-state.ts";

const WORKSPACE_START_WAIT_MS = 1000;

export interface WorkstreamStartDeps {
	getWorkspaceState(): WorkspaceState | null;
	waitForWorkspaceState(): Promise<WorkspaceState | null>;
	launchStatePath(): string;
	findByWorktreeLabel(filePath: string, worktreeLabel: string, repo?: string): WorkstreamLaunchRecord | null;
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
		findByWorktreeLabel: findWorkstreamLaunchByWorktreeLabel,
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
	ctx: ExtensionContext,
	deps: WorkstreamStartDeps,
): Promise<RepoWorkspaceState | null> {
	let workspace = deps.getWorkspaceState();
	if (!workspace) workspace = await deps.waitForWorkspaceState();
	if (!workspace?.repo?.isRepo) {
		ctx.ui.notify("Cannot start a workstream because this session is not in a repository workspace.", "error");
		return null;
	}
	return workspace as RepoWorkspaceState;
}

// The workstream id is inferred from the current worktree: `pi --workstream` is a bare boolean flag, and the
// pane Herdr opens (or a manual `cd <worktree-path>`) always runs inside the staged copilot/<name> worktree.
export async function startWorkstream(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	deps = defaultWorkstreamStartDeps(),
): Promise<void> {
	let statePath: string;
	let record: WorkstreamLaunchRecord | null;
	try {
		const workspace = await resolveWorkspaceForWorkstreamStart(ctx, deps);
		if (!workspace) return;

		const worktreeLabel = workspace.activeWorktree?.label;
		if (!worktreeLabel) {
			ctx.ui.notify(
				"Run `pi --workstream` from inside the workstream worktree Herdr set up; this session is not in a worktree.",
				"error",
			);
			return;
		}

		statePath = deps.launchStatePath();
		record = deps.findByWorktreeLabel(statePath, worktreeLabel, workspace.repo.name);
		if (!record) {
			ctx.ui.notify(
				`No staged workstream found for worktree "${worktreeLabel}". Confirm it with copilot (list_workstream_launches).`,
				"error",
			);
			return;
		}
	} catch (err) {
		ctx.ui.notify(`Could not load the staged workstream for this worktree: ${errorMessage(err)}`, "error");
		return;
	}
	if (!record) return;

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
	// Boolean flag: `pi --workstream` is bare (a string flag would reject the bare form with "requires a value").
	pi.registerFlag("workstream", {
		description: "Start the staged workstream for the current worktree (run bare inside the worktree Herdr set up).",
		type: "boolean",
	});
	pi.registerFlag("copilot", {
		description: "Locked repo-copilot session (takes precedence over --workstream).",
		type: "boolean",
	});

	// Flag presence marks this as a workstream session, so the product role and Explore posture are set on presence
	// alone — before the record lookup. This is intentional: a --workstream invocation is a workstream attempt, and a
	// failed lookup only notifies an error (the posture is benign and the user re-runs from the correct worktree).
	registerSessionProductRoleProvider({
		resolveProductRole: () =>
			pi.getFlag("copilot") !== undefined || pi.getFlag("workstream") === undefined ? null : "workstream_agent",
	});

	pi.on("session_start", async (event, ctx) => {
		if (pi.getFlag("workstream") === undefined) return;
		if (pi.getFlag("copilot") !== undefined) {
			ctx.ui.notify("copilot takes precedence; --workstream is ignored for this session.", "warning");
			return;
		}
		// Force Explore on every workstream session_start (including reload) so the session always begins from a
		// planning posture; the executor/supervisor mode set at plan approval only persists within a single process.
		deps.enterExploreMode(event, ctx);
		await startWorkstream(pi, ctx, deps);
	});
}
