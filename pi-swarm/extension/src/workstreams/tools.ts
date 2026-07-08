import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { readWorktreeSetupCommand } from "pi-core/platform/config.ts";
import {
	getWorkspaceState,
	listWorkspaceWorktrees,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "pi-core/platform/workspace.ts";
import { runWorktreeSetup, shouldRunWorktreeSetup, type WorktreeSetupResult } from "pi-core/workspace/setup.ts";
import { getOrCreateWorktree, type WorktreeResult } from "pi-core/workspace/worktree.ts";
import { copilotWorktreeTarget } from "pi-core/workspace/worktree-target.ts";
import type { DaemonClient } from "../agents/daemon/client.ts";
import {
	getWorkstream,
	listWorkstreams,
	type WorkstreamAgentView,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "../agents/daemon/client.ts";
import { resolveDaemonPaths } from "../agents/daemon/paths.ts";
import { type HerdrWorkstreamOpenResult, openWorkstreamInHerdr } from "./herdr.ts";
import { generateWorkstreamName as generateGenericWorkstreamName } from "./name.ts";

export interface LaunchWorkstreamParams {
	source: {
		dossierPath: string;
		repoPagePath?: string;
	};
	workstream: {
		label: string;
		brief: string;
		constraints?: string;
		worktreeSlug?: string;
	};
	workstreamId?: string;
}

export interface LaunchWorkstreamResultDetails {
	status: "launched" | "carried" | "failed";
	message: string;
	id?: string;
	slug?: string;
	worktree?: {
		label: string;
		path?: string;
		branch?: string | null;
		created?: boolean;
	};
	setup_summary?: WorktreeSetupResult | { status: string; message: string };
	herdr_summary?: unknown;
	next_step: string;
}

type LaunchWorkstreamToolResult = {
	content: { type: "text"; text: string }[];
	details: LaunchWorkstreamResultDetails;
	isError?: boolean;
};

export interface ListWorkstreamsParams {
	repo?: string;
	dossierPath?: string;
	query?: string;
	status?: "open" | "closed";
}

export interface ListWorkstreamsResultDetails {
	status: "ok" | "failed";
	message: string;
	count: number;
	workstreams: WorkstreamSummary[];
	workstream?: WorkstreamDetail;
	next_step: string;
}

type ListWorkstreamsToolResult = {
	content: { type: "text"; text: string }[];
	details: ListWorkstreamsResultDetails;
	isError?: boolean;
};

export interface SetWorkstreamStatusParams {
	workstream: string;
	status: "open" | "closed";
}

export interface SetWorkstreamStatusResultDetails {
	status: "updated" | "not_found" | "invalid_status" | "failed";
	message: string;
	workstream: string;
	next_step: string;
}

type SetWorkstreamStatusToolResult = {
	content: { type: "text"; text: string }[];
	details: SetWorkstreamStatusResultDetails;
	isError?: boolean;
};

export interface WorkstreamToolsDeps {
	getWorkspaceState(): WorkspaceState | null;
	listWorkspaceWorktrees(): Promise<WorkspaceWorktree[]>;
	getOrCreateWorktree(
		pi: ExtensionAPI,
		repoRoot: string,
		repoName: string,
		label: string,
		branchName: string | null,
	): Promise<WorktreeResult>;
	readWorktreeSetupCommand(repoName: string): string | null;
	runWorktreeSetup(
		pi: ExtensionAPI,
		opts: { command: string; worktreeDir: string; repoRoot: string },
	): Promise<WorktreeSetupResult>;
	openWorkstreamInHerdr(
		pi: Pick<ExtensionAPI, "exec">,
		workspace: { protectedRoot?: string; repo?: { root?: string }; launchCwd?: string; hasUI?: boolean },
		worktree: { path: string; label: string },
		env: NodeJS.ProcessEnv,
	): Promise<HerdrWorkstreamOpenResult>;
	generateWorkstreamName(isTaken: (name: string) => boolean): string;
	getClient(): Promise<DaemonClient | null>;
	resolveSocketPath(): string;
	getWorkstreamDetail(socketPath: string, identifier: string): Promise<WorkstreamDetail | null>;
	listWorkstreamSummaries(
		socketPath: string,
		filter: { status?: string; repo?: string; dossierPath?: string; query?: string },
	): Promise<WorkstreamSummary[] | null>;
}

export function defaultWorkstreamToolsDeps(getConnection: () => Promise<unknown>): WorkstreamToolsDeps {
	return {
		getWorkspaceState,
		listWorkspaceWorktrees,
		getOrCreateWorktree,
		readWorktreeSetupCommand,
		runWorktreeSetup,
		openWorkstreamInHerdr,
		generateWorkstreamName: (isTaken) => generateGenericWorkstreamName({ isTaken }),
		getClient: async () => {
			const connection = await getConnection();
			if (!connection) return null;
			const { createDaemonClient } = await import("../agents/daemon/client.ts");
			return createDaemonClient(connection as Parameters<typeof createDaemonClient>[0]);
		},
		resolveSocketPath: () => process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
		getWorkstreamDetail: (socketPath, identifier) => getWorkstream(socketPath, identifier),
		listWorkstreamSummaries: (socketPath, filter) => listWorkstreams(socketPath, filter),
	};
}

function errorMessage(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
}

function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

function workstreamLaunchCommand(slug: string): string {
	return `pi --workstream=${slug}`;
}

function workstreamLaunchCommandFromPath(path: string, slug: string): string {
	return `cd ${shellQuote(path)} && ${workstreamLaunchCommand(slug)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalTrimmedString(value: unknown): string | undefined {
	if (value === undefined) return undefined;
	if (typeof value !== "string") return undefined;
	const trimmed = value.trim();
	return trimmed ? trimmed : undefined;
}

function requiredTrimmedString(
	value: unknown,
	path: string,
	tool = "launch_workstream",
): { ok: true; value: string } | { ok: false; message: string } {
	if (typeof value !== "string" || !value.trim()) {
		return { ok: false, message: `${tool} requires a non-empty ${path}.` };
	}
	return { ok: true, value: value.trim() };
}

export function parseLaunchWorkstreamParams(
	params: unknown,
): { ok: true; value: LaunchWorkstreamParams } | { ok: false; message: string } {
	if (!isRecord(params) || !isRecord(params.source) || !isRecord(params.workstream)) {
		return { ok: false, message: "launch_workstream requires source and workstream objects." };
	}

	const dossierPath = requiredTrimmedString(params.source.dossierPath, "source.dossierPath");
	if (!dossierPath.ok) return dossierPath;
	const label = requiredTrimmedString(params.workstream.label, "workstream.label");
	if (!label.ok) return label;
	const brief = requiredTrimmedString(params.workstream.brief, "workstream.brief");
	if (!brief.ok) return brief;
	const carryIdentifier = optionalTrimmedString(params.workstream_id);

	return {
		ok: true,
		value: {
			source: {
				dossierPath: dossierPath.value,
				...(optionalTrimmedString(params.source.repoPagePath)
					? { repoPagePath: optionalTrimmedString(params.source.repoPagePath) }
					: {}),
			},
			workstream: {
				label: label.value,
				brief: brief.value,
				...(optionalTrimmedString(params.workstream.constraints)
					? { constraints: optionalTrimmedString(params.workstream.constraints) }
					: {}),
				...(optionalTrimmedString(params.workstream.worktreeSlug)
					? { worktreeSlug: optionalTrimmedString(params.workstream.worktreeSlug) }
					: {}),
			},
			...(carryIdentifier ? { workstreamId: carryIdentifier } : {}),
		},
	};
}

function parseListWorkstreamsParams(params: unknown): ListWorkstreamsParams {
	if (!isRecord(params)) return {};
	const query =
		optionalTrimmedString(params.query) ?? optionalTrimmedString(params.slug) ?? optionalTrimmedString(params.label);
	return {
		...(optionalTrimmedString(params.repo) ? { repo: optionalTrimmedString(params.repo) } : {}),
		...(optionalTrimmedString(params.dossierPath) ? { dossierPath: optionalTrimmedString(params.dossierPath) } : {}),
		...(query ? { query } : {}),
		...(params.status === "open" || params.status === "closed" ? { status: params.status } : {}),
	};
}

function parseSetWorkstreamStatusParams(
	params: unknown,
): { ok: true; value: SetWorkstreamStatusParams } | { ok: false; message: string } {
	if (!isRecord(params)) return { ok: false, message: "set_workstream_status requires workstream and status." };
	const workstream = requiredTrimmedString(params.workstream, "workstream", "set_workstream_status");
	if (!workstream.ok) return workstream;
	const status = params.status;
	if (status !== "open" && status !== "closed") {
		return { ok: false, message: "set_workstream_status requires status to be 'open' or 'closed'." };
	}
	return { ok: true, value: { workstream: workstream.value, status } };
}

function textResult(details: LaunchWorkstreamResultDetails, isError = false): LaunchWorkstreamToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

function listTextResult(details: ListWorkstreamsResultDetails, isError = false): ListWorkstreamsToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

function statusTextResult(details: SetWorkstreamStatusResultDetails, isError = false): SetWorkstreamStatusToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

function workspaceForHerdr(workspace: WorkspaceState | null, hasUI: boolean) {
	return {
		...(workspace?.protectedRoot ? { protectedRoot: workspace.protectedRoot } : {}),
		...(workspace?.repo?.root ? { repo: { root: workspace.repo.root } } : {}),
		...(workspace?.launchCwd ? { launchCwd: workspace.launchCwd } : {}),
		hasUI,
	};
}

function resultWorktree(worktree: WorktreeResult): LaunchWorkstreamResultDetails["worktree"] {
	return {
		label: worktree.label,
		path: worktree.worktreeDir,
		branch: worktree.branch,
		created: worktree.created,
	};
}

function failedLaunchDetails(message: string, nextStep: string): LaunchWorkstreamResultDetails {
	return { status: "failed", message, next_step: nextStep };
}

async function provisionWorktree(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	repoRoot: string,
	repo: string,
	worktreeLabel: string,
	branchName: string | null,
): Promise<{ worktree: WorktreeResult; error?: string }> {
	try {
		const worktree = await deps.getOrCreateWorktree(pi, repoRoot, repo, worktreeLabel, branchName);
		return { worktree };
	} catch (err) {
		return {
			worktree: { worktreeDir: "", label: worktreeLabel, branch: branchName ?? "", created: false },
			error: errorMessage(err),
		};
	}
}

async function runSetup(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	repoRoot: string,
	repo: string,
	worktree: WorktreeResult,
): Promise<WorktreeSetupResult | { status: string; message: string }> {
	const setupCommand = deps.readWorktreeSetupCommand(repo);
	if (!shouldRunWorktreeSetup(worktree.created, setupCommand)) {
		return {
			status: "skipped",
			message: setupCommand
				? "Worktree setup skipped because the worktree was not newly created."
				: "Worktree setup skipped because no setup command is configured.",
		};
	}
	try {
		return await deps.runWorktreeSetup(pi, {
			command: setupCommand as string,
			worktreeDir: worktree.worktreeDir,
			repoRoot,
		});
	} catch (err) {
		return { status: "failed", message: `Worktree setup threw an error; continuing. (${errorMessage(err)})` };
	}
}

async function openHerdr(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	workspace: WorkspaceState | null,
	ctx: ExtensionContext,
	worktree: WorktreeResult,
): Promise<HerdrWorkstreamOpenResult> {
	return await deps.openWorkstreamInHerdr(
		pi,
		workspaceForHerdr(workspace, ctx.hasUI),
		{ path: worktree.worktreeDir, label: worktree.label },
		process.env,
	);
}

function herdrToSummary(herdr: HerdrWorkstreamOpenResult): unknown {
	return herdr;
}

function buildNextStep(herdr: HerdrWorkstreamOpenResult, worktree: WorktreeResult, slug: string): string {
	const pathCommand = workstreamLaunchCommandFromPath(worktree.worktreeDir, slug);
	if (herdr.status === "opened") {
		return `Herdr opened a pane for worktree ${worktree.label}. In that pane, run \`${workstreamLaunchCommand(slug)}\`.`;
	}
	if (herdr.status === "skipped") {
		return `Worktree ${worktree.label} is ready, but no Herdr pane was opened (${herdr.message}). Run \`${pathCommand}\`.`;
	}
	return `Worktree ${worktree.label} is ready, but the Herdr pane failed to open (${herdr.message}). Run \`${pathCommand}\`.`;
}

async function executeCreateWorkstream(
	parsed: LaunchWorkstreamParams,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	deps: WorkstreamToolsDeps,
): Promise<LaunchWorkstreamToolResult> {
	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo || !workspace.repo.root) {
		return textResult(
			failedLaunchDetails(
				"launch_workstream requires a current git repository workspace.",
				"Open a repository-backed Basecamp workspace, then call launch_workstream again.",
			),
			true,
		);
	}

	const repo = workspace.repo.name;
	const repoRoot = workspace.repo.root;
	const socketPath = deps.resolveSocketPath();

	const client = await deps.getClient();
	if (!client) {
		return textResult(
			failedLaunchDetails(
				"basecamp swarm daemon is not connected; cannot create a workstream.",
				"Ensure the daemon is running (it starts automatically for top-level sessions), then call launch_workstream again.",
			),
			true,
		);
	}

	const workName = parsed.workstream.worktreeSlug ?? parsed.workstream.label;
	const maxSlugAttempts = 25;

	let slug: string | null = null;
	let worktreeTarget: ReturnType<typeof copilotWorktreeTarget> | null = null;

	try {
		for (let attempt = 0; attempt < maxSlugAttempts; attempt += 1) {
			const candidate = deps.generateWorkstreamName(() => false);
			const existing = await deps.getWorkstreamDetail(socketPath, candidate);
			if (existing) continue;
			slug = candidate;
			worktreeTarget = copilotWorktreeTarget(workName, candidate);
			break;
		}
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not generate a unique workstream slug: ${errorMessage(err)}`,
				"Call launch_workstream again; if collisions continue, inspect existing workstreams.",
			),
			true,
		);
	}

	if (!slug || !worktreeTarget) {
		return textResult(
			failedLaunchDetails(
				`Could not generate a unique workstream slug after ${maxSlugAttempts} attempts.`,
				"Call launch_workstream again; if collisions continue, inspect existing workstreams.",
			),
			true,
		);
	}

	// Check the derived bt/ branch isn't already checked out
	let existingWorktrees: WorkspaceWorktree[];
	try {
		existingWorktrees = await deps.listWorkspaceWorktrees();
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not list existing worktrees: ${errorMessage(err)}`,
				"Fix worktree listing for this repository, then call launch_workstream again.",
			),
			true,
		);
	}
	if (worktreeTarget.branchName && existingWorktrees.some((wt) => wt.branch === worktreeTarget.branchName)) {
		return textResult(
			failedLaunchDetails(
				`The branch ${worktreeTarget.branchName} is already checked out in another worktree for this repo.`,
				"Call launch_workstream again with a distinct workstream.worktreeSlug so the initial branch name is not already checked out.",
			),
			true,
		);
	}

	// Provision the worktree
	const { worktree, error: provisionError } = await provisionWorktree(
		deps,
		pi,
		repoRoot,
		repo,
		worktreeTarget.worktreeLabel,
		worktreeTarget.branchName,
	);
	if (provisionError) {
		return textResult(
			failedLaunchDetails(
				`Failed to provision worktree ${worktreeTarget.worktreeLabel}: ${provisionError}`,
				"Fix worktree provisioning or choose a different workstream.worktreeSlug, then retry.",
			),
			true,
		);
	}

	// Run setup (transient — not persisted)
	const setupSummary = await runSetup(deps, pi, repoRoot, repo, worktree);

	// Open Herdr (transient — not persisted)
	const herdrResult = await openHerdr(deps, pi, workspace, ctx, worktree);

	// Create the workstream in the daemon
	const workstreamId = `ws_${randomUUID()}`;
	let createResult: Awaited<ReturnType<DaemonClient["createWorkstream"]>>;
	try {
		createResult = await client.createWorkstream({
			workstreamId,
			slug,
			label: parsed.workstream.label,
			brief: parsed.workstream.brief,
			sourceDossierPath: parsed.source.dossierPath,
			...(parsed.workstream.constraints ? { constraints: parsed.workstream.constraints } : {}),
			...(parsed.source.repoPagePath ? { sourceRepoPagePath: parsed.source.repoPagePath } : {}),
		});
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Failed to create workstream in daemon: ${errorMessage(err)}`,
				"The worktree is provisioned; retry launch_workstream (the slug will be regenerated).",
			),
			true,
		);
	}

	// On slug_conflict, regenerate and retry the create (worktree is reusable if label matches)
	if (createResult.status === "slug_conflict") {
		for (let retry = 0; retry < maxSlugAttempts; retry += 1) {
			const retrySlug = deps.generateWorkstreamName(() => false);
			const retryExisting = await deps.getWorkstreamDetail(socketPath, retrySlug);
			if (retryExisting) continue;
			try {
				createResult = await client.createWorkstream({
					workstreamId,
					slug: retrySlug,
					label: parsed.workstream.label,
					brief: parsed.workstream.brief,
					sourceDossierPath: parsed.source.dossierPath,
					...(parsed.workstream.constraints ? { constraints: parsed.workstream.constraints } : {}),
					...(parsed.source.repoPagePath ? { sourceRepoPagePath: parsed.source.repoPagePath } : {}),
				});
			} catch (err) {
				return textResult(
					failedLaunchDetails(
						`Failed to create workstream in daemon: ${errorMessage(err)}`,
						"The worktree is provisioned; retry launch_workstream.",
					),
					true,
				);
			}
			if (createResult.status === "created") {
				slug = retrySlug;
				break;
			}
			if (createResult.status === "slug_conflict") continue;
			break;
		}
	}

	if (createResult.status !== "created") {
		return textResult(
			failedLaunchDetails(
				`Daemon rejected workstream creation: ${createResult.error ?? createResult.status}`,
				"The worktree is provisioned; inspect the daemon error and retry launch_workstream.",
			),
			true,
		);
	}

	const nextStep = buildNextStep(herdrResult, worktree, slug);

	return textResult({
		status: "launched",
		message: `Workstream "${parsed.workstream.label}" created as ${slug}.`,
		id: createResult.workstream_id ?? workstreamId,
		slug,
		worktree: resultWorktree(worktree),
		setup_summary: setupSummary,
		herdr_summary: herdrToSummary(herdrResult),
		next_step: nextStep,
	});
}

async function executeCarryWorkstream(
	parsed: LaunchWorkstreamParams,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	deps: WorkstreamToolsDeps,
): Promise<LaunchWorkstreamToolResult> {
	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo || !workspace.repo.root) {
		return textResult(
			failedLaunchDetails(
				"launch_workstream requires a current git repository workspace.",
				"Open a repository-backed Basecamp workspace, then call launch_workstream again.",
			),
			true,
		);
	}

	const repo = workspace.repo.name;
	const repoRoot = workspace.repo.root;
	const socketPath = deps.resolveSocketPath();
	const identifier = parsed.workstreamId as string;

	let detail: WorkstreamDetail | null;
	try {
		detail = await deps.getWorkstreamDetail(socketPath, identifier);
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not resolve workstream "${identifier}": ${errorMessage(err)}`,
				"Check the workstream id or slug with list_workstreams, then call launch_workstream again.",
			),
			true,
		);
	}
	if (!detail?.slug) {
		return textResult(
			failedLaunchDetails(
				`No workstream found for "${identifier}".`,
				"Use list_workstreams to find an existing workstream id or slug, then pass it as the workstream parameter.",
			),
			true,
		);
	}

	const slug = detail.slug;
	const worktreeTarget = copilotWorktreeTarget(parsed.workstream.worktreeSlug ?? parsed.workstream.label, slug);

	// getOrCreateWorktree is idempotent — reuses if present
	const { worktree, error: provisionError } = await provisionWorktree(
		deps,
		pi,
		repoRoot,
		repo,
		worktreeTarget.worktreeLabel,
		worktreeTarget.branchName,
	);
	if (provisionError) {
		return textResult(
			failedLaunchDetails(
				`Failed to provision worktree ${worktreeTarget.worktreeLabel}: ${provisionError}`,
				"Fix worktree provisioning, then retry launch_workstream with the same workstream identifier.",
			),
			true,
		);
	}

	const setupSummary = await runSetup(deps, pi, repoRoot, repo, worktree);
	const herdrResult = await openHerdr(deps, pi, workspace, ctx, worktree);
	const nextStep = buildNextStep(herdrResult, worktree, slug);

	return textResult({
		status: "carried",
		message: `Workstream "${detail.label ?? slug}" carried to ${repo}.`,
		id: detail.id ?? undefined,
		slug,
		worktree: resultWorktree(worktree),
		setup_summary: setupSummary,
		herdr_summary: herdrToSummary(herdrResult),
		next_step: nextStep,
	});
}

export async function executeLaunchWorkstream(
	params: unknown,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	_signal?: AbortSignal,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<LaunchWorkstreamToolResult> {
	const parsed = parseLaunchWorkstreamParams(params);
	if (!parsed.ok) {
		return textResult(
			failedLaunchDetails(parsed.message, "Call launch_workstream again with non-empty required fields."),
			true,
		);
	}

	if (parsed.value.workstreamId) {
		return executeCarryWorkstream(parsed.value, pi, ctx, deps);
	}
	return executeCreateWorkstream(parsed.value, pi, ctx, deps);
}

export async function executeListWorkstreams(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<ListWorkstreamsToolResult> {
	const parsed = parseListWorkstreamsParams(params);
	const socketPath = deps.resolveSocketPath();

	// Single-identifier lookup: if query is an exact slug or id, fetch the detail with agents view
	if (parsed.query && !parsed.status && !parsed.repo && !parsed.dossierPath) {
		try {
			const detail = await deps.getWorkstreamDetail(socketPath, parsed.query);
			if (detail) {
				return listTextResult({
					status: "ok",
					message: `Found workstream ${detail.slug ?? detail.id}.`,
					count: 1,
					workstreams: [detail],
					workstream: detail,
					next_step: formatAgentsNextStep(detail.agents),
				});
			}
		} catch {
			// fall through to list
		}
	}

	let summaries: WorkstreamSummary[] | null;
	try {
		summaries = await deps.listWorkstreamSummaries(socketPath, {
			...(parsed.status ? { status: parsed.status } : {}),
			...(parsed.repo ? { repo: parsed.repo } : {}),
			...(parsed.dossierPath ? { dossierPath: parsed.dossierPath } : {}),
			...(parsed.query ? { query: parsed.query } : {}),
		});
	} catch (err) {
		return listTextResult(
			{
				status: "failed",
				message: `Could not list workstreams: ${errorMessage(err)}`,
				count: 0,
				workstreams: [],
				next_step: "Ensure the daemon is running, then call list_workstreams again.",
			},
			true,
		);
	}

	if (summaries === null) {
		return listTextResult(
			{
				status: "failed",
				message: "basecamp swarm daemon is not connected; cannot list workstreams.",
				count: 0,
				workstreams: [],
				next_step:
					"Ensure the daemon is running (it starts automatically for top-level sessions), then call list_workstreams again.",
			},
			true,
		);
	}

	return listTextResult({
		status: "ok",
		message: `Found ${summaries.length} workstream${summaries.length === 1 ? "" : "s"}.`,
		count: summaries.length,
		workstreams: summaries,
		next_step:
			"For a single workstream's agents view, pass its slug or id as the query parameter. Use set_workstream_status to open or close a workstream.",
	});
}

function formatAgentsNextStep(agents: WorkstreamAgentView[]): string {
	if (agents.length === 0) {
		return "No agents are attached to this workstream yet. Run pi --workstream=<slug> in the workstream worktree to attach.";
	}
	const handles = agents
		.filter((a) => a.agent_handle)
		.map((a) => a.agent_handle)
		.join(", ");
	return `Attached agents: ${handles}. Use message_agent or ask_agent to reach them by handle.`;
}

export async function executeSetWorkstreamStatus(
	params: unknown,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<SetWorkstreamStatusToolResult> {
	const parsed = parseSetWorkstreamStatusParams(params);
	if (!parsed.ok) {
		return statusTextResult(
			{
				status: "failed",
				message: parsed.message,
				workstream: "",
				next_step: "Call set_workstream_status again with a workstream id/slug and status 'open' or 'closed'.",
			},
			true,
		);
	}

	const client = await deps.getClient();
	if (!client) {
		return statusTextResult(
			{
				status: "failed",
				message: "basecamp swarm daemon is not connected; cannot update workstream status.",
				workstream: parsed.value.workstream,
				next_step: "Ensure the daemon is running, then call set_workstream_status again.",
			},
			true,
		);
	}

	let result: Awaited<ReturnType<DaemonClient["updateWorkstream"]>>;
	try {
		result = await client.updateWorkstream({
			workstream: parsed.value.workstream,
			status: parsed.value.status,
		});
	} catch (err) {
		return statusTextResult(
			{
				status: "failed",
				message: `Could not update workstream status: ${errorMessage(err)}`,
				workstream: parsed.value.workstream,
				next_step: "Retry set_workstream_status; if the error persists, check the daemon.",
			},
			true,
		);
	}

	if (result.status === "updated") {
		return statusTextResult({
			status: "updated",
			message: `Workstream "${parsed.value.workstream}" is now ${parsed.value.status}.`,
			workstream: parsed.value.workstream,
			next_step: "Use list_workstreams to verify the updated status.",
		});
	}
	if (result.status === "not_found") {
		return statusTextResult(
			{
				status: "not_found",
				message: `No workstream found for "${parsed.value.workstream}".`,
				workstream: parsed.value.workstream,
				next_step: "Use list_workstreams to find the correct id or slug, then call set_workstream_status again.",
			},
			true,
		);
	}
	if (result.status === "invalid_status") {
		return statusTextResult(
			{
				status: "invalid_status",
				message: `Status "${parsed.value.status}" is not valid for this workstream.`,
				workstream: parsed.value.workstream,
				next_step: "Use 'open' or 'closed' as the status.",
			},
			true,
		);
	}
	return statusTextResult(
		{
			status: "failed",
			message: `Daemon rejected status update: ${result.error ?? result.status}`,
			workstream: parsed.value.workstream,
			next_step: "Check the daemon error and retry set_workstream_status.",
		},
		true,
	);
}

export function registerWorkstreamTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<unknown>,
	_deps?: WorkstreamToolsDeps,
): void {
	const deps = _deps ?? defaultWorkstreamToolsDeps(getConnection);

	pi.registerTool({
		name: "launch_workstream",
		label: "Launch Workstream",
		description:
			"Stage a workstream from a dossier brief: provision one generically-named worktree (copilot/<three-words>), open a Herdr pane on it, and create the workstream in the daemon. Pass an existing workstream id or slug to carry it into the current repo (reuses the worktree idempotently). The user runs `pi --workstream=<slug>` in that pane to start the agent.",
		promptSnippet: "Stage or carry a Herdr workstream worktree + pane",
		parameters: Type.Object(
			{
				source: Type.Object(
					{
						dossierPath: Type.String({ description: "Path to the dossier that defines the launch context." }),
						repoPagePath: Type.Optional(
							Type.String({ description: "Optional path to the repository cockpit/page for additional context." }),
						),
					},
					{ additionalProperties: false },
				),
				workstream: Type.Object(
					{
						label: Type.String({
							description: "Human-readable workstream label (used in the brief).",
						}),
						brief: Type.String({
							description: "Workstream brief the launched agent will receive via pi --workstream.",
						}),
						constraints: Type.Optional(Type.String({ description: "Optional constraints for the workstream." })),
						worktreeSlug: Type.Optional(
							Type.String({
								description:
									"Optional slug used to derive the initial bt/ branch name (the worktree itself gets a generic name).",
							}),
						),
					},
					{ additionalProperties: false },
				),
				workstream_id: Type.Optional(
					Type.String({
						description:
							"Optional existing workstream id or slug to carry into the current repo. When omitted, a new workstream is created.",
					}),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params, signal, _onUpdate, ctx) {
			return await executeLaunchWorkstream(params, pi, ctx, signal, deps);
		},
	});

	pi.registerTool({
		name: "list_workstreams",
		label: "List Workstreams",
		description:
			"List workstreams from the daemon. Filters by repo, dossierPath, query (slug/label substring), and status (open|closed). For a single-identifier lookup (query only), returns the workstream detail with the joined agents view.",
		promptSnippet: "List workstreams from the daemon",
		parameters: Type.Object(
			{
				repo: Type.Optional(Type.String({ description: "Filter to workstreams with agents in this repo." })),
				dossierPath: Type.Optional(Type.String({ description: "Filter to workstreams from this dossier path." })),
				query: Type.Optional(
					Type.String({
						description:
							"Case-insensitive substring filter for slug or label. When used alone, returns the workstream detail with agents.",
					}),
				),
				slug: Type.Optional(Type.String({ description: "Alias for query." })),
				label: Type.Optional(Type.String({ description: "Alias for query." })),
				status: Type.Optional(
					Type.Union([Type.Literal("open"), Type.Literal("closed")], {
						description: "Filter by workstream status.",
					}),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeListWorkstreams(params, deps);
		},
	});

	pi.registerTool({
		name: "set_workstream_status",
		label: "Set Workstream Status",
		description: "Set the status of a workstream to 'open' or 'closed' via the daemon.",
		promptSnippet: "Open or close a workstream",
		parameters: Type.Object(
			{
				workstream: Type.String({ description: "Workstream id or slug." }),
				status: Type.Union([Type.Literal("open"), Type.Literal("closed")], {
					description: "New status for the workstream.",
				}),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params) {
			return await executeSetWorkstreamStatus(params, deps);
		},
	});
}
