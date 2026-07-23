/**
 * Transient-workspace provisioning for dispatched agents (issue #310, Phase 1, revised).
 *
 * Deliverable runs (persona `deliverable: true` — the worker) mint an `agent/<handle>`
 * branch from a CLEAN parent HEAD; a retask continues the outstanding branch. Report runs
 * (every other persona, ad-hoc) and asks get branchless detached workspaces at the parent's
 * HEAD — or a snapshot commit of its dirty state, so reviewers see uncommitted WIP without
 * the snapshot ever entering branch topology. Non-repo sessions provision nothing.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { AGENT_BRANCH_NAMESPACE } from "../../git/constants.ts";
import {
	branchTip,
	createSnapshotCommit,
	detectDefaultBranch,
	gitOutput,
	isMergedInto,
	isWorktreeClean,
} from "../../git/repo.ts";
import { createAgentWorktree, deleteBranch, removeWorktree } from "../../git/worktrees/lifecycle.ts";
import { readWorktreeSetupCommand } from "../../host/config.ts";
import { runWorktreeSetup } from "../../project/workspace/setup.ts";
import type { WorkspaceState } from "../../project/workspace/state.ts";

export function agentBranchName(agentHandle: string): string {
	return `${AGENT_BRANCH_NAMESPACE}${agentHandle}`;
}

export type AgentWorkspaceKind = "deliverable" | "report" | "ask";

export type AgentWorkspaceRequest =
	| {
			kind: "deliverable";
			/** Durable public handle keying the run's branch. */
			agentHandle: string;
			/** Continuing an existing daemon-validated agent? Only retasks may continue a branch. */
			isRetask: boolean;
			runToken: string;
			agentName: string;
	  }
	| { kind: "report"; runToken: string; agentName: string }
	| {
			kind: "ask";
			/** The ask target's handle — the answerer detaches at that agent's branch tip when it exists. */
			targetHandle: string;
			runToken: string;
			agentName: string;
	  };

export interface AgentWorkspaceProvision {
	kind: AgentWorkspaceKind;
	worktreeDir: string;
	/** Worktree label (`agent-<runToken>/<name>`) — stamped on the child env pre-adoption. */
	label: string;
	/** The run's branch — set for deliverable runs only; report/ask workspaces are detached. */
	branch: string | null;
	/** Commit OID the run started from; teardown's zero-commit check compares against this. */
	baseOid: string;
	/** True when this provision minted the branch (teardown may delete it only then). */
	branchCreated: boolean;
	repoRoot: string;
	/** Nonfatal setup-hook failure, surfaced in the dispatch result. */
	setupWarning?: string;
}

function workspaceLabelName(name: string): string {
	const cleaned = name.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "");
	return cleaned || "agent";
}

function friendlyGitError(error: unknown): Error {
	const message = error instanceof Error ? error.message : String(error);
	if (/already (?:used by|checked out)/i.test(message)) {
		return new Error(
			"The agent's branch is still checked out in a previous run's workspace (likely still tearing down). Retry shortly.",
		);
	}
	if (/unknown revision|ambiguous argument 'HEAD'|Needed a single revision/i.test(message)) {
		return new Error("This repository has no commits yet; make an initial commit before dispatching agents.");
	}
	return error instanceof Error ? error : new Error(message);
}

async function detachedBaseOid(pi: ExtensionAPI, parentWorktree: string): Promise<string> {
	if (await isWorktreeClean(pi, parentWorktree)) {
		return await gitOutput(pi, parentWorktree, ["rev-parse", "HEAD"]);
	}
	return await createSnapshotCommit(pi, parentWorktree);
}

/** Best-effort integration candidates for the merged-branch check: parent branch + default. */
async function integrationBranches(pi: ExtensionAPI, repoRoot: string, parentWorktree: string): Promise<string[]> {
	const candidates = new Set<string>();
	try {
		const parentBranch = await gitOutput(pi, parentWorktree, ["branch", "--show-current"]);
		if (parentBranch) candidates.add(parentBranch);
	} catch {
		/* detached or unreadable parent — skip */
	}
	try {
		candidates.add(await detectDefaultBranch(pi, repoRoot));
	} catch {
		/* no recognizable default branch — skip */
	}
	return [...candidates];
}

// Clean-base rule: a deliverable branch roots on committed history only, so integration is
// always a plain merge and a WIP snapshot can never enter durable history. Applies whenever
// a branch root is minted; continuing an outstanding branch mints nothing.
async function requireCleanBase(pi: ExtensionAPI, parentWorktree: string): Promise<string> {
	if (!(await isWorktreeClean(pi, parentWorktree))) {
		throw new Error(
			"Parent worktree has uncommitted changes. Deliverable agents branch from committed history only — " +
				"commit your WIP first, then re-dispatch.",
		);
	}
	return await gitOutput(pi, parentWorktree, ["rev-parse", "HEAD"]);
}

async function resolveDeliverableCheckout(
	pi: ExtensionAPI,
	request: Extract<AgentWorkspaceRequest, { kind: "deliverable" }>,
	repoRoot: string,
	parentWorktree: string,
): Promise<{ branch: string; baseOid: string; branchCreated: boolean }> {
	const branch = agentBranchName(request.agentHandle);
	const tip = await branchTip(pi, repoRoot, branch);

	if (tip && !request.isRetask) {
		// A fresh dispatch must never adopt a pre-existing branch: the handle is new, so the
		// branch is stale residue (or a foreign collision) — refuse rather than continue it.
		throw new Error(
			`Branch ${branch} already exists but this is not a retask of that agent. ` +
				`Delete the stale branch (or merge it) and retry.`,
		);
	}

	if (tip) {
		for (const candidate of await integrationBranches(pi, repoRoot, parentWorktree)) {
			if (await isMergedInto(pi, repoRoot, branch, candidate)) {
				// Integrated: the work is in the candidate's history — start fresh from the parent.
				await deleteBranch(pi, repoRoot, branch);
				return { branch, baseOid: await requireCleanBase(pi, parentWorktree), branchCreated: true };
			}
		}
		// Outstanding: continue the agent's own branch so its memory and tree agree.
		return { branch, baseOid: tip, branchCreated: false };
	}

	return { branch, baseOid: await requireCleanBase(pi, parentWorktree), branchCreated: true };
}

/**
 * Provision a dispatched run's own workspace. Returns null for a session without a repo
 * (nothing to isolate — the run keeps the launch cwd and a report-only toolset). Setup
 * hooks run for deliverable and report runs (blocking, nonfatal); asks skip them for latency.
 */
export async function provisionAgentWorkspace(
	pi: ExtensionAPI,
	request: AgentWorkspaceRequest,
	workspace: WorkspaceState | null,
): Promise<AgentWorkspaceProvision | null> {
	const repo = workspace?.repo;
	if (!repo?.root || !repo.name) return null;

	const repoRoot = workspace?.protectedRoot ?? repo.root;
	const parentWorktree = workspace?.activeWorktree?.path ?? repoRoot;
	const label = `agent-${request.runToken}/${workspaceLabelName(request.agentName)}`;

	try {
		if (request.kind === "deliverable") {
			const checkout = await resolveDeliverableCheckout(pi, request, repoRoot, parentWorktree);
			const worktree = await createAgentWorktree(
				pi,
				repoRoot,
				repo.name,
				label,
				checkout.branchCreated
					? { kind: "new-branch", branch: checkout.branch, baseRef: checkout.baseOid }
					: { kind: "existing-branch", branch: checkout.branch },
			);
			const provision: AgentWorkspaceProvision = {
				kind: request.kind,
				...checkout,
				...worktreeFields(worktree, label),
				repoRoot,
			};
			await runSetupHook(pi, repo.name, repoRoot, provision);
			return provision;
		}

		const baseOid =
			request.kind === "ask"
				? ((await branchTip(pi, repoRoot, agentBranchName(request.targetHandle))) ??
					(await detachedBaseOid(pi, parentWorktree)))
				: await detachedBaseOid(pi, parentWorktree);
		const worktree = await createAgentWorktree(pi, repoRoot, repo.name, label, { kind: "detached", baseRef: baseOid });
		const provision: AgentWorkspaceProvision = {
			kind: request.kind,
			...worktreeFields(worktree, label),
			branch: null,
			baseOid,
			branchCreated: false,
			repoRoot,
		};
		if (request.kind === "report") await runSetupHook(pi, repo.name, repoRoot, provision);
		return provision;
	} catch (error) {
		throw friendlyGitError(error);
	}
}

function worktreeFields(worktree: { worktreeDir: string; branch: string | null }, label: string) {
	return { worktreeDir: worktree.worktreeDir, label, branch: worktree.branch };
}

async function runSetupHook(
	pi: ExtensionAPI,
	repoName: string,
	repoRoot: string,
	provision: AgentWorkspaceProvision,
): Promise<void> {
	const command = readWorktreeSetupCommand(repoName);
	if (!command) return;
	const result = await runWorktreeSetup(pi, { command, worktreeDir: provision.worktreeDir, repoRoot });
	if (result.exitCode !== 0 || result.timedOut) {
		const reason = result.timedOut ? "timed out" : `exited ${result.exitCode}`;
		provision.setupWarning = `Workspace setup hook ${reason}: ${result.stderrTail || "(no stderr)"}`;
	}
}

/**
 * Best-effort teardown of a just-provisioned workspace after a dispatch failure. Deletes the
 * branch only when this provision minted it — a retask's outstanding branch is prior work and
 * must survive a failed re-dispatch. The daemon owns teardown once a dispatch is accepted.
 */
export async function discardAgentWorkspace(
	pi: ExtensionAPI,
	provision: AgentWorkspaceProvision | null,
): Promise<void> {
	if (!provision) return;
	try {
		await removeWorktree(pi, provision.repoRoot, provision.worktreeDir, { force: true });
		if (provision.branch && provision.branchCreated) {
			await deleteBranch(pi, provision.repoRoot, provision.branch);
		}
	} catch {
		// best-effort; the daemon-restart reconcile and session-start sweep are the backstops.
	}
}
