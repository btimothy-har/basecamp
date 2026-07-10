import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { isCopilotLaunch } from "#core/agent-mode/copilot.ts";
import { setAgentMode } from "#core/agent-mode/index.ts";
import { registerSessionProductRoleProvider } from "#core/platform/product-role.ts";
import {
	getWorkspaceService,
	getWorkspaceState,
	type RepoContext,
	type WorkspaceState,
} from "#core/platform/workspace.ts";
import type { DaemonClient, WorkstreamDetail } from "../agents/daemon/client.ts";
import { resolveDaemonPaths } from "../agents/daemon/paths.ts";
import { errorMessage } from "../agents/errors.ts";
import { buildWorkstreamLaunchBrief } from "./brief.ts";

// Cap only; waitForWorkspaceState resolves early via the workspace onChange event, so a generous
// cap costs nothing on the fast path and gives slow repo/worktree initialization time to complete.
const WORKSPACE_START_WAIT_MS = 5000;

const COPILOT_WORKTREE_PREFIX = "copilot/";

export interface WorkstreamStartDeps {
	getWorkspaceState(): WorkspaceState | null;
	waitForWorkspaceState(): Promise<WorkspaceState | null>;
	resolveSocketPath(): string;
	getWorkstreamDetail(socketPath: string, identifier: string): Promise<WorkstreamDetail | null>;
	getClient(): Promise<DaemonClient | null>;
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

function defaultEnterExploreMode(_event: SessionStartEvent, ctx: ExtensionContext): void {
	try {
		// Core's session_start (registered first) already initialized state.
		setAgentMode("planning");
	} catch (err) {
		ctx.ui.notify(`basecamp: could not enter Explore mode for workstream — ${errorMessage(err)}`, "warning");
	}
}

export function defaultWorkstreamStartDeps(getConnection: () => Promise<unknown>): WorkstreamStartDeps {
	return {
		getWorkspaceState,
		waitForWorkspaceState,
		resolveSocketPath: () => process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
		getWorkstreamDetail: async (socketPath, identifier) => {
			const { getWorkstream } = await import("../agents/daemon/client.ts");
			return getWorkstream(socketPath, identifier);
		},
		getClient: async () => {
			const connection = await getConnection();
			if (!connection) return null;
			const { createDaemonClient } = await import("../agents/daemon/client.ts");
			return createDaemonClient(connection as Parameters<typeof createDaemonClient>[0]);
		},
		enterExploreMode: defaultEnterExploreMode,
	};
}

function inferSlugFromWorktreeLabel(label: string): string | null {
	if (!label.startsWith(COPILOT_WORKTREE_PREFIX)) return null;
	const slug = label.slice(COPILOT_WORKTREE_PREFIX.length);
	return slug || null;
}

function buildStartBrief(
	detail: WorkstreamDetail,
	worktree: { label: string; path: string; branch: string | null },
): string {
	return buildWorkstreamLaunchBrief({
		source: {
			dossierPath: detail.source_dossier_path ?? "(dossier path not recorded)",
			...(detail.source_repo_page_path ? { repoPagePath: detail.source_repo_page_path } : {}),
		},
		workstream: {
			label: detail.label ?? detail.slug ?? "(untitled)",
			brief: detail.brief ?? "(no brief recorded)",
			...(detail.constraints ? { constraints: detail.constraints } : {}),
		},
		worktree,
	});
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

interface AttachOutcome {
	status: "attached" | "not_found" | "failed";
	message: string;
}

async function attachToWorkstream(
	deps: WorkstreamStartDeps,
	identifier: string,
	repo: string,
	worktreeLabel: string,
): Promise<AttachOutcome> {
	const client = await deps.getClient();
	if (!client) {
		return { status: "failed", message: "basecamp swarm daemon is not connected; could not attach." };
	}
	try {
		const result = await client.attachWorkstreamAgent({
			workstream: identifier,
			repo,
			worktreeLabel,
			status: "attached",
		});
		if (result.status === "attached") {
			return { status: "attached", message: "Attached this session as a workstream agent." };
		}
		if (result.status === "not_found") {
			return { status: "not_found", message: `Workstream "${identifier}" was not found in the daemon.` };
		}
		return { status: "failed", message: `Daemon rejected attach: ${result.error ?? result.status}` };
	} catch (err) {
		return { status: "failed", message: `Could not attach to workstream: ${errorMessage(err)}` };
	}
}

export async function startWorkstream(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	flagValue: string | undefined,
	deps: WorkstreamStartDeps,
): Promise<void> {
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

	const socketPath = deps.resolveSocketPath();

	let identifier: string;
	let inferredFromWorktree = false;
	if (flagValue?.trim()) {
		identifier = flagValue.trim();
	} else {
		const inferredSlug = inferSlugFromWorktreeLabel(worktreeLabel);
		if (!inferredSlug) {
			ctx.ui.notify(
				`Worktree "${worktreeLabel}" is not a copilot/<slug> worktree; pass --workstream=<slug|id> to specify the workstream.`,
				"error",
			);
			return;
		}
		identifier = inferredSlug;
		inferredFromWorktree = true;
	}

	let detail: WorkstreamDetail | null;
	try {
		detail = await deps.getWorkstreamDetail(socketPath, identifier);
	} catch (err) {
		const context = inferredFromWorktree ? " from worktree label" : "";
		ctx.ui.notify(`Could not resolve workstream "${identifier}"${context}: ${errorMessage(err)}`, "error");
		return;
	}

	if (!detail) {
		ctx.ui.notify(`No workstream found for "${identifier}". Use list_workstreams to confirm the id or slug.`, "error");
		return;
	}

	const repo = workspace.repo.name;
	const worktree = {
		label: worktreeLabel,
		path: workspace.activeWorktree?.path ?? worktreeLabel,
		branch: workspace.activeWorktree?.branch ?? null,
	};

	const attachOutcome = await attachToWorkstream(deps, identifier, repo, worktreeLabel);
	if (attachOutcome.status === "not_found") {
		ctx.ui.notify(attachOutcome.message, "warning");
	} else if (attachOutcome.status === "failed") {
		ctx.ui.notify(attachOutcome.message, "warning");
	}

	const brief = buildStartBrief(detail, worktree);
	const attachNote =
		attachOutcome.status === "attached"
			? "\n\nThis session is attached to the workstream as a workstream agent."
			: attachOutcome.status === "not_found"
				? `\n\nNote: the daemon did not find workstream "${identifier}" for attach; the brief is still provided. Copilot may not be able to route to this session automatically.`
				: `\n\nNote: attach to the daemon failed (${attachOutcome.message}); the brief is still provided. Copilot may not be able to route to this session automatically.`;
	pi.sendUserMessage(`${brief}${attachNote}`);
}

// pi has no optional-value flag: a `string` flag rejects the bare form ("requires a value") and a `boolean`
// flag discards any `=value`. Register boolean so bare `--workstream` works and `--workstream=<slug|id>` is
// accepted without error, then recover the explicit value from argv.
export function parseWorkstreamFlagValue(argv: readonly string[]): string | undefined {
	for (const arg of argv) {
		const match = /^--workstream=(.*)$/.exec(arg);
		if (match) {
			const value = match[1]?.trim();
			return value ? value : undefined;
		}
	}
	return undefined;
}

export function registerWorkstreamStartup(
	pi: ExtensionAPI,
	getConnection: () => Promise<unknown>,
	_deps?: WorkstreamStartDeps,
): void {
	const deps = _deps ?? defaultWorkstreamStartDeps(getConnection);

	pi.registerFlag("workstream", {
		description:
			"Start the workstream for the current worktree. Bare --workstream infers the workstream from the copilot/<slug> worktree label; --workstream=<slug|id> resolves explicitly.",
		type: "boolean",
	});

	// --copilot is owned by core/pi and takes precedence; read it via isCopilotLaunch() rather than re-registering.
	registerSessionProductRoleProvider({
		resolveProductRole: () => (isCopilotLaunch() || pi.getFlag("workstream") === undefined ? null : "workstream_agent"),
	});

	pi.on("session_start", async (event, ctx) => {
		if (pi.getFlag("workstream") === undefined) return;
		if (isCopilotLaunch()) {
			ctx.ui.notify("copilot takes precedence; --workstream is ignored for this session.", "warning");
			return;
		}
		deps.enterExploreMode(event, ctx);
		await startWorkstream(pi, ctx, parseWorkstreamFlagValue(process.argv), deps);
	});
}
