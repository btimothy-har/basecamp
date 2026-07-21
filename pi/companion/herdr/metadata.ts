import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { processScoped } from "#core/global-registry.ts";
import { getAgentDepth } from "#core/host/env.ts";
import { exec } from "#core/host/exec.ts";
import type { CompanionSnapshot } from "../snapshot/model.ts";

export const HERDR_METADATA_SOURCE = "basecamp.pi";
export const HERDR_DISPLAY_AGENT = "pi";
export const HERDR_LIFECYCLE_SOURCE = "herdr:pi";

const TITLE_LIMIT = 80;
const DISPLAY_AGENT_LIMIT = 80;
const CUSTOM_STATUS_LIMIT = 32;

interface HerdrMetadataState {
	seq: number;
}

export interface HerdrMetadataEnv {
	herdrEnv?: string;
	herdrPaneId?: string;
	herdrSocketPath?: string;
	agentDepth: number;
}

export interface HerdrStatusContext {
	primaryIdle: boolean;
	waitingForAgents: boolean;
	activeAgentCount: number | null;
}

const DEFAULT_STATUS_CONTEXT: HerdrStatusContext = {
	primaryIdle: false,
	waitingForAgents: false,
	activeAgentCount: null,
};

export function createHerdrMetadataSeqBase(nowMs = Date.now(), pid = process.pid): number {
	return Math.trunc(nowMs) * 1_000 + (Math.abs(Math.trunc(pid)) % 1_000);
}

// Surviving state: the metadata sequence outlives /reload.
const metadataSeqBase = createHerdrMetadataSeqBase();
const getHerdrMetadataState = processScoped<HerdrMetadataState>("basecamp.herdr.metadata", () => ({
	seq: metadataSeqBase,
}));
getHerdrMetadataState().seq = Math.max(getHerdrMetadataState().seq, metadataSeqBase);

export function resetHerdrMetadataSeqForTest(seq = 0): void {
	getHerdrMetadataState().seq = seq;
}

export function nextHerdrMetadataSeq(): number {
	const state = getHerdrMetadataState();
	state.seq += 1;
	return state.seq;
}

export function shouldReportHerdrMetadata(input: HerdrMetadataEnv): boolean {
	return (
		input.herdrEnv === "1" && Boolean(input.herdrPaneId) && Boolean(input.herdrSocketPath) && input.agentDepth === 0
	);
}

export function sanitizeHerdrMetadataField(value: string, limit: number): string {
	return value
		.replace(/[\p{Cc}\p{Cf}]+/gu, " ")
		.replace(/\s+/g, " ")
		.trim()
		.slice(0, limit);
}

function firstSanitizedMetadataField(candidates: Array<string | null | undefined>, limit: number): string {
	for (const candidate of candidates) {
		if (candidate === null || candidate === undefined) continue;
		const value = sanitizeHerdrMetadataField(candidate, limit);
		if (value) return value;
	}
	return "";
}

function waitingOnAgentsLabel(status: HerdrStatusContext): string | null {
	const hasActiveAgents = status.activeAgentCount !== null && status.activeAgentCount > 0;
	if (!status.waitingForAgents && !(status.primaryIdle && hasActiveAgents)) return null;
	if (!hasActiveAgents) return "waiting on agents";
	return status.activeAgentCount === 1 ? "waiting on 1 agent" : `waiting on ${status.activeAgentCount} agents`;
}

export function buildHerdrMetadata(
	snapshot: CompanionSnapshot,
	status: HerdrStatusContext = DEFAULT_STATUS_CONTEXT,
): {
	title: string;
	displayAgent: string;
	customStatus: string;
} {
	const activeTaskLabel = snapshot.tasks.find((task) => task.status === "active")?.label;
	return {
		title: firstSanitizedMetadataField([snapshot.title, snapshot.repoName, snapshot.sessionId], TITLE_LIMIT),
		displayAgent: sanitizeHerdrMetadataField(HERDR_DISPLAY_AGENT, DISPLAY_AGENT_LIMIT),
		customStatus: firstSanitizedMetadataField(
			[waitingOnAgentsLabel(status), activeTaskLabel, snapshot.worktree?.label, snapshot.agentMode, snapshot.repoName],
			CUSTOM_STATUS_LIMIT,
		),
	};
}

export function buildHerdrMetadataArgs(
	paneId: string,
	snapshot: CompanionSnapshot,
	seq: number,
	status: HerdrStatusContext = DEFAULT_STATUS_CONTEXT,
): string[] {
	const metadata = buildHerdrMetadata(snapshot, status);
	return [
		"pane",
		"report-metadata",
		paneId,
		"--source",
		HERDR_METADATA_SOURCE,
		"--agent",
		HERDR_DISPLAY_AGENT,
		"--applies-to-source",
		HERDR_LIFECYCLE_SOURCE,
		"--display-agent",
		metadata.displayAgent,
		"--title",
		metadata.title,
		"--custom-status",
		metadata.customStatus,
		"--seq",
		String(seq),
	];
}

export async function reportHerdrMetadata(
	pi: ExtensionAPI,
	snapshot: CompanionSnapshot,
	status: HerdrStatusContext = DEFAULT_STATUS_CONTEXT,
): Promise<void> {
	try {
		const env: HerdrMetadataEnv = {
			herdrEnv: process.env.HERDR_ENV,
			herdrPaneId: process.env.HERDR_PANE_ID,
			herdrSocketPath: process.env.HERDR_SOCKET_PATH,
			agentDepth: getAgentDepth(),
		};
		if (!shouldReportHerdrMetadata(env) || !env.herdrPaneId) return;
		await exec(pi, "herdr", buildHerdrMetadataArgs(env.herdrPaneId, snapshot, nextHerdrMetadataSeq(), status));
	} catch {
		// best effort
	}
}
