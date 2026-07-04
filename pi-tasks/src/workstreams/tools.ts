import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { readWorktreeSetupCommand } from "pi-core/platform/config.ts";
import {
	getWorkspaceState,
	listWorkspaceWorktrees,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "pi-core/platform/workspace.ts";
import { shortSessionId } from "pi-core/session/session-id.ts";
import { runWorktreeSetup, type WorktreeSetupResult } from "pi-core/workspace/setup.ts";
import { getOrCreateWorktree, type WorktreeResult } from "pi-core/workspace/worktree.ts";
import { suggestWorktreeTarget } from "../planning/worktree-choices.ts";
import { shouldRunWorktreeSetup } from "../planning/worktree-setup.ts";
import { type HerdrWorkstreamOpenResult, openWorkstreamInHerdr } from "./herdr.ts";
import {
	appendWorkstreamLaunchRecordWithAvailableId,
	buildWorkstreamLaunchFingerprint,
	findDuplicateWorkstreamLaunch,
	listWorkstreamLaunchRecords,
	updateFailedWorkstreamLaunchRecord,
	updateWorkstreamLaunchRecord,
	type WorkstreamLaunchAppendResult,
	type WorkstreamLaunchRecord,
	type WorkstreamLaunchRecordDraft,
	type WorkstreamLaunchRecordUpdate,
	workstreamLaunchStatePath,
} from "./launch-state.ts";

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
}

export interface LaunchWorkstreamResultDetails {
	status: "launched" | "existing_launch" | "failed";
	message: string;
	id?: string;
	launch_record?: WorkstreamLaunchRecord;
	worktree?: {
		label: string;
		path?: string;
		branch?: string | null;
		created?: boolean;
	};
	agentHandle?: string;
	setup_summary?: unknown;
	herdr_summary?: unknown;
	launch_summary?: unknown;
	next_step: string;
}

type LaunchWorkstreamToolResult = {
	content: { type: "text"; text: string }[];
	details: LaunchWorkstreamResultDetails;
	isError?: boolean;
};

export interface ListWorkstreamLaunchesParams {
	dossierPath?: string;
	label?: string;
	includeBrief?: boolean;
}

export interface ListWorkstreamLaunchEntry {
	id: string;
	label: string;
	brief?: string;
	briefPreview?: string;
	constraints?: string;
	dossierPath: string;
	repoPagePath?: string;
	worktree: {
		label: string;
		path?: string;
		branch?: string;
	};
	agentHandle?: string;
	agentType?: string;
	setupStatus: WorkstreamLaunchRecord["setup"]["status"];
	herdrStatus: WorkstreamLaunchRecord["herdr"]["status"];
	launchStatus: WorkstreamLaunchRecord["launch"]["status"];
	createdAt: string;
	updatedAt: string;
}

export interface ListWorkstreamLaunchesResultDetails {
	status: "ok" | "no_workspace";
	message: string;
	count: number;
	launches: ListWorkstreamLaunchEntry[];
	next_step: string;
}

type ListWorkstreamLaunchesToolResult = {
	content: { type: "text"; text: string }[];
	details: ListWorkstreamLaunchesResultDetails;
	isError?: boolean;
};

interface PersistedLaunchStoreDeps {
	launchStatePath(): string;
	appendRecordWithAvailableId(
		filePath: string,
		record: WorkstreamLaunchRecordDraft,
		lookup: { repo?: string; fingerprint?: string; worktreeLabel?: string },
		baseLabel: string,
	): WorkstreamLaunchAppendResult;
	updateRecord(
		filePath: string,
		id: string,
		updates: WorkstreamLaunchRecordUpdate,
		now?: string,
	): WorkstreamLaunchRecord | null;
	updateFailedRecord(
		filePath: string,
		id: string,
		updates: WorkstreamLaunchRecordUpdate,
		now?: string,
	): WorkstreamLaunchRecord | null;
	findDuplicate(
		filePath: string,
		lookup: { repo?: string; fingerprint?: string; worktreeLabel?: string },
	): WorkstreamLaunchRecord | null;
}

interface ListWorkstreamLaunchesStoreDeps {
	launchStatePath(): string;
	listRecords(filePath: string, filter: { repo?: string; dossierPath?: string }): WorkstreamLaunchRecord[];
}

export interface LaunchWorkstreamDeps {
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
	store: PersistedLaunchStoreDeps;
	now(): string;
}

export function defaultLaunchWorkstreamDeps(): LaunchWorkstreamDeps {
	return {
		getWorkspaceState,
		listWorkspaceWorktrees,
		getOrCreateWorktree,
		readWorktreeSetupCommand,
		runWorktreeSetup,
		openWorkstreamInHerdr,
		store: {
			launchStatePath: workstreamLaunchStatePath,
			appendRecordWithAvailableId: appendWorkstreamLaunchRecordWithAvailableId,
			updateRecord: updateWorkstreamLaunchRecord,
			updateFailedRecord: updateFailedWorkstreamLaunchRecord,
			findDuplicate: findDuplicateWorkstreamLaunch,
		},
		now: () => new Date().toISOString(),
	};
}

export interface ListWorkstreamLaunchesDeps {
	getWorkspaceState(): WorkspaceState | null;
	store: ListWorkstreamLaunchesStoreDeps;
}

export function defaultListWorkstreamLaunchesDeps(): ListWorkstreamLaunchesDeps {
	return {
		getWorkspaceState,
		store: {
			launchStatePath: workstreamLaunchStatePath,
			listRecords: listWorkstreamLaunchRecords,
		},
	};
}

function textResult(details: LaunchWorkstreamResultDetails, isError = false): LaunchWorkstreamToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

function listTextResult(
	details: ListWorkstreamLaunchesResultDetails,
	isError = false,
): ListWorkstreamLaunchesToolResult {
	return {
		content: [{ type: "text", text: JSON.stringify(details) }],
		details,
		...(isError ? { isError: true } : {}),
	};
}

function errorMessage(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
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
): { ok: true; value: string } | { ok: false; message: string } {
	if (typeof value !== "string" || !value.trim()) {
		return { ok: false, message: `launch_workstream requires a non-empty ${path}.` };
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
		},
	};
}

function parseListWorkstreamLaunchesParams(params: unknown): ListWorkstreamLaunchesParams {
	if (!isRecord(params)) return {};
	return {
		...(optionalTrimmedString(params.dossierPath) ? { dossierPath: optionalTrimmedString(params.dossierPath) } : {}),
		...(optionalTrimmedString(params.label) ? { label: optionalTrimmedString(params.label) } : {}),
		...(params.includeBrief === true ? { includeBrief: true } : {}),
	};
}

const BRIEF_PREVIEW_MAX_LENGTH = 200;

function briefPreview(brief: string): string {
	if (brief.length <= BRIEF_PREVIEW_MAX_LENGTH) return brief;
	return `${brief.slice(0, BRIEF_PREVIEW_MAX_LENGTH - 1).trimEnd()}…`;
}

function listEntry(record: WorkstreamLaunchRecord, includeBrief: boolean): ListWorkstreamLaunchEntry {
	return {
		id: record.id,
		label: record.workstream.label,
		...(includeBrief ? { brief: record.workstream.brief } : { briefPreview: briefPreview(record.workstream.brief) }),
		...(record.workstream.constraints ? { constraints: record.workstream.constraints } : {}),
		dossierPath: record.source.dossierPath,
		...(record.source.repoPagePath ? { repoPagePath: record.source.repoPagePath } : {}),
		worktree: {
			label: record.worktree.label,
			...(record.worktree.path ? { path: record.worktree.path } : {}),
			...(record.worktree.branch ? { branch: record.worktree.branch } : {}),
		},
		...(record.agent.handle ? { agentHandle: record.agent.handle } : {}),
		...(record.agent.type ? { agentType: record.agent.type } : {}),
		setupStatus: record.setup.status,
		herdrStatus: record.herdr.status,
		launchStatus: record.launch.status,
		createdAt: record.createdAt,
		updatedAt: record.updatedAt,
	};
}

export function executeListWorkstreamLaunches(
	params: unknown,
	_ctx: ExtensionContext,
	deps: ListWorkstreamLaunchesDeps = defaultListWorkstreamLaunchesDeps(),
): ListWorkstreamLaunchesToolResult {
	const parsed = parseListWorkstreamLaunchesParams(params);
	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo) {
		return listTextResult(
			{
				status: "no_workspace",
				message: "list_workstream_launches requires a current git repository workspace.",
				count: 0,
				launches: [],
				next_step: "Open a repository-backed Basecamp workspace, then call list_workstream_launches again.",
			},
			true,
		);
	}

	const repo = workspace.repo.name;
	const labelFilter = parsed.label?.toLowerCase();
	const launches = deps.store
		.listRecords(deps.store.launchStatePath(), { repo, dossierPath: parsed.dossierPath })
		.filter((record) => !labelFilter || record.workstream.label.toLowerCase().includes(labelFilter))
		.toSorted((left, right) => right.createdAt.localeCompare(left.createdAt))
		.map((record) => listEntry(record, parsed.includeBrief === true));

	return listTextResult({
		status: "ok",
		message: `Found ${launches.length} launched workstream-agent record${launches.length === 1 ? "" : "s"} for ${repo}.`,
		count: launches.length,
		launches,
		next_step:
			"Use a launch's agentHandle to ask or message the relevant Herdr workstream agent for current context; do not treat these launch records as durable workstream status.",
	});
}

function recordWorktree(worktree: WorktreeResult): WorkstreamLaunchRecord["worktree"] {
	return {
		label: worktree.label,
		path: worktree.worktreeDir,
		...(worktree.branch ? { branch: worktree.branch } : {}),
		created: worktree.created,
	};
}

function resultWorktree(record: WorkstreamLaunchRecord): LaunchWorkstreamResultDetails["worktree"] {
	return {
		label: record.worktree.label,
		...(record.worktree.path ? { path: record.worktree.path } : {}),
		...(record.worktree.branch !== undefined ? { branch: record.worktree.branch } : {}),
		...(record.worktree.created !== undefined ? { created: record.worktree.created } : {}),
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

function launchRecordSummary(record: WorkstreamLaunchRecord) {
	return {
		setup: record.setup,
		herdr: record.herdr,
		launch: record.launch,
	};
}

async function updateRecord(
	deps: LaunchWorkstreamDeps,
	filePath: string,
	current: WorkstreamLaunchRecord,
	updates: WorkstreamLaunchRecordUpdate,
): Promise<WorkstreamLaunchRecord> {
	const updated = deps.store.updateRecord(filePath, current.id, updates, deps.now());
	return updated ?? current;
}

function reclaimFailedRecord(
	deps: LaunchWorkstreamDeps,
	filePath: string,
	current: WorkstreamLaunchRecord,
	updates: WorkstreamLaunchRecordUpdate,
): WorkstreamLaunchRecord | null {
	return deps.store.updateFailedRecord(filePath, current.id, updates, deps.now());
}

function failedDetails(
	message: string,
	nextStep: string,
	record?: WorkstreamLaunchRecord,
): LaunchWorkstreamResultDetails {
	return {
		status: "failed",
		message,
		...(record
			? { launch_record: record, worktree: resultWorktree(record), launch_summary: launchRecordSummary(record) }
			: {}),
		next_step: nextStep,
	};
}

function existingLaunchResult(
	record: WorkstreamLaunchRecord,
	matchedByFingerprint: boolean,
): LaunchWorkstreamResultDetails {
	const message = matchedByFingerprint
		? `A workstream launch already exists for this dossier and label (${record.id}).`
		: `Worktree ${record.worktree.label} is already staged under a different workstream (${record.id}).`;
	const nextStep = matchedByFingerprint
		? record.agent.handle
			? `Continue with the existing workstream agent (handle ${record.agent.handle}).`
			: `Open worktree ${record.worktree.label}, run \`pi\`, then \`/workstream ${record.id}\` (no agent has attached yet).`
		: `Choose a different workstream.worktreeSlug to stage a separate worktree, or continue the existing workstream ${record.id}.`;
	return {
		status: "existing_launch",
		message,
		id: record.id,
		launch_record: record,
		worktree: resultWorktree(record),
		...(record.agent.handle ? { agentHandle: record.agent.handle } : {}),
		setup_summary: record.setup,
		herdr_summary: record.herdr,
		launch_summary: record.launch,
		next_step: nextStep,
	};
}

function workstreamUpdate(
	workstream: LaunchWorkstreamParams["workstream"],
): WorkstreamLaunchRecordUpdate["workstream"] {
	return {
		label: workstream.label,
		brief: workstream.brief,
		constraints: workstream.constraints,
	};
}

function sourceUpdate(source: LaunchWorkstreamParams["source"]): WorkstreamLaunchRecordUpdate["source"] {
	return {
		dossierPath: source.dossierPath,
		repoPagePath: source.repoPagePath,
	};
}

function stagingReset(
	message: string,
	repo: string,
	fingerprint: string,
	params: LaunchWorkstreamParams,
): WorkstreamLaunchRecordUpdate {
	return {
		repo,
		fingerprint,
		source: sourceUpdate(params.source),
		workstream: workstreamUpdate(params.workstream),
		setup: { status: "pending", message: "Re-staging after a previous failed launch." },
		herdr: { status: "pending", message: "Herdr pane open is pending." },
		launch: { status: "running", message },
	};
}

export async function executeLaunchWorkstream(
	params: unknown,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	_signal?: AbortSignal,
	deps: LaunchWorkstreamDeps = defaultLaunchWorkstreamDeps(),
): Promise<LaunchWorkstreamToolResult> {
	const parsed = parseLaunchWorkstreamParams(params);
	if (!parsed.ok) {
		return textResult(
			failedDetails(parsed.message, "Call launch_workstream again with non-empty required fields."),
			true,
		);
	}

	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo || !workspace.repo.root) {
		return textResult(
			failedDetails(
				"launch_workstream requires a current git repository workspace.",
				"Open a repository-backed Basecamp workspace, then call launch_workstream again.",
			),
			true,
		);
	}

	const repo = workspace.repo.name;
	const repoRoot = workspace.repo.root;
	const sessionTag = shortSessionId(ctx.sessionManager.getSessionId());
	const target = suggestWorktreeTarget(
		parsed.value.workstream.label,
		parsed.value.workstream.worktreeSlug ?? null,
		sessionTag,
	);
	const fingerprint = buildWorkstreamLaunchFingerprint({
		repo,
		dossierPath: parsed.value.source.dossierPath,
		label: parsed.value.workstream.label,
	});
	const statePath = deps.store.launchStatePath();
	const duplicateLookup = {
		repo,
		fingerprint,
		worktreeLabel: target.worktreeLabel,
	};

	// Reuse a non-failed matching launch; a failed record is a reclaimable tombstone we re-stage in place.
	const duplicate = deps.store.findDuplicate(statePath, duplicateLookup);
	if (duplicate && duplicate.launch.status !== "failed") {
		return textResult(existingLaunchResult(duplicate, duplicate.fingerprint === fingerprint));
	}

	let record: WorkstreamLaunchRecord;
	if (duplicate) {
		try {
			const reclaimed = reclaimFailedRecord(
				deps,
				statePath,
				duplicate,
				stagingReset("Re-staging workstream after a previous failure.", repo, fingerprint, parsed.value),
			);
			if (!reclaimed) {
				const current = deps.store.findDuplicate(statePath, duplicateLookup);
				if (current && current.launch.status !== "failed") {
					return textResult(existingLaunchResult(current, current.fingerprint === fingerprint));
				}
				return textResult(
					failedDetails(
						`Could not reclaim failed workstream launch ${duplicate.id} because it changed while retrying.`,
						"Refresh the workstream launch list, then continue the existing launch or retry.",
						current ?? duplicate,
					),
					true,
				);
			}
			record = reclaimed;
		} catch (err) {
			return textResult(
				failedDetails(
					`Could not reclaim failed workstream launch ${duplicate.id}: ${errorMessage(err)}`,
					"Fix workstream launch state persistence, then call launch_workstream again.",
					duplicate,
				),
				true,
			);
		}
	} else {
		// Refuse to silently adopt an existing worktree that has no launch record.
		let existingWorktrees: WorkspaceWorktree[];
		try {
			existingWorktrees = await deps.listWorkspaceWorktrees();
		} catch (err) {
			return textResult(
				failedDetails(
					`Could not list existing worktrees: ${errorMessage(err)}`,
					"Fix worktree listing for this repository, then call launch_workstream again.",
				),
				true,
			);
		}
		if (existingWorktrees.some((worktree) => worktree.label === target.worktreeLabel)) {
			return textResult(
				failedDetails(
					`Worktree label ${target.worktreeLabel} already exists without a matching launch record; choose a different workstream.worktreeSlug and retry.`,
					"Call launch_workstream again with a different workstream.worktreeSlug so an existing potentially dirty worktree is not reused silently.",
				),
				true,
			);
		}

		const now = deps.now();
		const initial: WorkstreamLaunchRecordDraft = {
			fingerprint,
			repo,
			source: parsed.value.source,
			workstream: {
				label: parsed.value.workstream.label,
				brief: parsed.value.workstream.brief,
				...(parsed.value.workstream.constraints ? { constraints: parsed.value.workstream.constraints } : {}),
			},
			worktree: {
				label: target.worktreeLabel,
				...(target.branchName ? { branch: target.branchName } : {}),
			},
			agent: {},
			setup: { status: "pending", message: "Worktree setup has not run yet." },
			herdr: { status: "pending", message: "Herdr pane open is pending worktree provisioning." },
			launch: { status: "running", message: "Workstream staging started." },
			createdAt: now,
			updatedAt: now,
		};

		try {
			const appended = deps.store.appendRecordWithAvailableId(
				statePath,
				initial,
				duplicateLookup,
				parsed.value.workstream.label,
			);
			if (appended.appended) {
				record = appended.record;
			} else if (appended.record.launch.status === "failed") {
				const reclaimed = reclaimFailedRecord(
					deps,
					statePath,
					appended.record,
					stagingReset("Re-staging workstream after a previous failure.", repo, fingerprint, parsed.value),
				);
				if (!reclaimed) {
					const current = deps.store.findDuplicate(statePath, duplicateLookup);
					if (current && current.launch.status !== "failed") {
						return textResult(existingLaunchResult(current, current.fingerprint === fingerprint));
					}
					return textResult(
						failedDetails(
							`Could not reclaim failed workstream launch ${appended.record.id} because it changed while retrying.`,
							"Refresh the workstream launch list, then continue the existing launch or retry.",
							current ?? appended.record,
						),
						true,
					);
				}
				record = reclaimed;
			} else {
				return textResult(existingLaunchResult(appended.record, appended.record.fingerprint === fingerprint));
			}
		} catch (err) {
			return textResult(
				failedDetails(
					`Could not persist workstream launch record: ${errorMessage(err)}`,
					"Fix workstream launch state persistence, then call launch_workstream again.",
				),
				true,
			);
		}
	}

	// Provision the worktree on disk WITHOUT activating it in this (copilot) session or mutating process.env.
	let worktree: WorktreeResult;
	try {
		worktree = await deps.getOrCreateWorktree(pi, repoRoot, repo, target.worktreeLabel, target.branchName);
		record = await updateRecord(deps, statePath, record, { worktree: recordWorktree(worktree) });
	} catch (err) {
		record = await updateRecord(deps, statePath, record, {
			setup: { status: "skipped", message: "Worktree setup skipped because provisioning failed." },
			herdr: { status: "skipped", message: "Herdr pane open skipped because provisioning failed." },
			launch: { status: "failed", error: errorMessage(err) },
		});
		return textResult(
			failedDetails(
				`Failed to provision worktree ${target.worktreeLabel}: ${errorMessage(err)}`,
				"Fix worktree provisioning or choose a different workstream.worktreeSlug, then retry.",
				record,
			),
			true,
		);
	}

	const setupCommand = deps.readWorktreeSetupCommand(repo);
	if (shouldRunWorktreeSetup(worktree.created, setupCommand)) {
		record = await updateRecord(deps, statePath, record, {
			setup: { status: "running", message: "Running worktree setup." },
		});
		try {
			const setupResult = await deps.runWorktreeSetup(pi, {
				command: setupCommand as string,
				worktreeDir: worktree.worktreeDir,
				repoRoot,
			});
			record = await updateRecord(deps, statePath, record, {
				setup:
					setupResult.timedOut || setupResult.exitCode !== 0
						? {
								status: "failed",
								message: setupResult.timedOut
									? "Worktree setup timed out; continuing."
									: `Worktree setup exited ${setupResult.exitCode}; continuing.`,
								error: setupResult.timedOut ? "timed_out" : `exit_code_${setupResult.exitCode}`,
							}
						: { status: "succeeded", message: "Worktree setup completed successfully." },
			});
		} catch (err) {
			record = await updateRecord(deps, statePath, record, {
				setup: {
					status: "failed",
					message: "Worktree setup threw an error; continuing.",
					error: errorMessage(err),
				},
			});
		}
	} else {
		const skippedMessage = setupCommand
			? "Worktree setup skipped because the worktree was not newly created."
			: "Worktree setup skipped because no setup command is configured.";
		record = await updateRecord(deps, statePath, record, {
			setup: { status: "skipped", message: skippedMessage },
		});
	}

	// Open a Herdr pane on the worktree (best-effort). No pi is launched; the user runs pi + /workstream <id>.
	const herdrResult = await deps.openWorkstreamInHerdr(
		pi,
		workspaceForHerdr(workspace, ctx.hasUI),
		{ path: worktree.worktreeDir, label: worktree.label },
		process.env,
	);
	if (herdrResult.status === "opened") {
		record = await updateRecord(deps, statePath, record, {
			herdr: { status: "succeeded", message: herdrResult.message },
		});
	} else if (herdrResult.status === "skipped") {
		record = await updateRecord(deps, statePath, record, {
			herdr: { status: "skipped", message: herdrResult.message },
		});
	} else {
		record = await updateRecord(deps, statePath, record, {
			herdr: {
				status: "failed",
				message: herdrResult.message,
				error:
					herdrResult.error ?? (herdrResult.exitCode === undefined ? undefined : `exit_code_${herdrResult.exitCode}`),
			},
		});
	}

	record = await updateRecord(deps, statePath, record, {
		launch: { status: "succeeded", message: "Workstream staged; awaiting /workstream in the pane." },
	});

	const startHint = `run \`pi\` in the new worktree pane, then \`/workstream ${record.id}\``;
	const nextStep =
		herdrResult.status === "opened"
			? `Herdr opened a pane for worktree ${record.worktree.label}. In that pane, ${startHint}.`
			: herdrResult.status === "skipped"
				? `Worktree ${record.worktree.label} is ready, but no Herdr pane was opened (${herdrResult.message}). Open the worktree, then ${startHint}.`
				: `Worktree ${record.worktree.label} is ready, but the Herdr pane failed to open (${herdrResult.message}). Open the worktree, then ${startHint}.`;

	return textResult({
		status: "launched",
		message: `Workstream "${parsed.value.workstream.label}" staged as ${record.id}.`,
		id: record.id,
		launch_record: record,
		worktree: resultWorktree(record),
		setup_summary: record.setup,
		herdr_summary: record.herdr,
		launch_summary: record.launch,
		next_step: nextStep,
	});
}

export function registerWorkstreamTools(
	pi: ExtensionAPI,
	deps = defaultLaunchWorkstreamDeps(),
	listDeps = defaultListWorkstreamLaunchesDeps(),
): void {
	pi.registerTool({
		name: "launch_workstream",
		label: "Launch Workstream",
		description:
			"Stage a workstream from a dossier brief: provision one dedicated worktree, open a Herdr pane on it, and record the workstream under a human-typeable id. The user then runs pi in that pane and /workstream <id> to start the agent. Does not dispatch an agent itself.",
		promptSnippet: "Stage a Herdr workstream worktree + pane under an id for /workstream",
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
							description: "Human-readable workstream label; also the basis for the /workstream id.",
						}),
						brief: Type.String({ description: "Workstream brief the launched agent will receive via /workstream." }),
						constraints: Type.Optional(Type.String({ description: "Optional constraints for the workstream." })),
						worktreeSlug: Type.Optional(
							Type.String({ description: "Optional slug used to derive the dedicated worktree label." }),
						),
					},
					{ additionalProperties: false },
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params, signal, _onUpdate, ctx) {
			return await executeLaunchWorkstream(params, pi, ctx, signal, deps);
		},
	});

	pi.registerTool({
		name: "list_workstream_launches",
		label: "List Workstream Launches",
		description:
			"List launched workstream-agent records for the current repo so callers can route to existing Herdr agents; this does not report durable workstream status.",
		promptSnippet: "List launched workstream-agent records for the current repo",
		parameters: Type.Object(
			{
				dossierPath: Type.Optional(Type.String({ description: "Only include launches from this dossier path." })),
				label: Type.Optional(
					Type.String({ description: "Case-insensitive substring filter for the launched workstream label." }),
				),
				includeBrief: Type.Optional(
					Type.Boolean({ description: "Include the full brief instead of a truncated preview." }),
				),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			return await executeListWorkstreamLaunches(params, ctx, listDeps);
		},
	});
}
