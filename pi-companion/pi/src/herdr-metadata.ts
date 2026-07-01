import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import type { CompanionSnapshot } from "./snapshot.ts";

export const HERDR_METADATA_SOURCE = "basecamp.pi";
export const HERDR_DISPLAY_AGENT = "pi";

const TITLE_LIMIT = 80;
const DISPLAY_AGENT_LIMIT = 80;
const CUSTOM_STATUS_LIMIT = 32;

interface HerdrMetadataState {
	seq: number;
}

const herdrMetadataKey = Symbol.for("basecamp.herdr.metadata");

type GlobalWithHerdrMetadata = typeof globalThis & {
	[herdrMetadataKey]?: HerdrMetadataState;
};

export interface HerdrMetadataEnv {
	herdrEnv?: string;
	herdrPaneId?: string;
	herdrSocketPath?: string;
	agentDepth: number;
}

function getHerdrMetadataState(): HerdrMetadataState {
	const globalObject = globalThis as GlobalWithHerdrMetadata;
	globalObject[herdrMetadataKey] ??= { seq: 0 };
	return globalObject[herdrMetadataKey];
}

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

export function buildHerdrMetadata(snapshot: CompanionSnapshot): {
	title: string;
	displayAgent: string;
	customStatus: string;
} {
	const activeTaskLabel = snapshot.tasks.find((task) => task.status === "active")?.label;
	return {
		title: sanitizeHerdrMetadataField(snapshot.title ?? snapshot.repoName ?? snapshot.sessionId, TITLE_LIMIT),
		displayAgent: sanitizeHerdrMetadataField(HERDR_DISPLAY_AGENT, DISPLAY_AGENT_LIMIT),
		customStatus: sanitizeHerdrMetadataField(
			activeTaskLabel ?? snapshot.worktree?.label ?? snapshot.agentMode ?? snapshot.repoName ?? "",
			CUSTOM_STATUS_LIMIT,
		),
	};
}

export function buildHerdrMetadataArgs(paneId: string, snapshot: CompanionSnapshot, seq: number): string[] {
	const metadata = buildHerdrMetadata(snapshot);
	return [
		"pane",
		"report-metadata",
		paneId,
		"--source",
		HERDR_METADATA_SOURCE,
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

export async function reportHerdrMetadata(pi: ExtensionAPI, snapshot: CompanionSnapshot): Promise<void> {
	try {
		const env: HerdrMetadataEnv = {
			herdrEnv: process.env.HERDR_ENV,
			herdrPaneId: process.env.HERDR_PANE_ID,
			herdrSocketPath: process.env.HERDR_SOCKET_PATH,
			agentDepth: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0"),
		};
		if (!shouldReportHerdrMetadata(env) || !env.herdrPaneId) return;
		await exec(pi, "herdr", buildHerdrMetadataArgs(env.herdrPaneId, snapshot, nextHerdrMetadataSeq()));
	} catch {
		// best effort
	}
}
