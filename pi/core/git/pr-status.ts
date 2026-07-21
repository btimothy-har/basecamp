import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PR_LOOKUP_TIMEOUT_MS = 10_000;
const PR_STATES = new Set<PullRequestState>(["OPEN", "MERGED", "CLOSED"]);

export type PullRequestState = "OPEN" | "MERGED" | "CLOSED";

export interface PullRequestStatus {
	number: number;
	url: string;
	state: PullRequestState;
	isDraft: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsePullRequestUrl(value: unknown): string | null {
	if (typeof value !== "string") return null;

	try {
		const url = new URL(value);
		if ((url.protocol !== "https:" && url.protocol !== "http:") || !url.hostname) return null;
		if (url.username || url.password) return null;
		return url.href;
	} catch {
		return null;
	}
}

function parsePullRequestStatus(output: string): PullRequestStatus | null {
	try {
		const value: unknown = JSON.parse(output);
		if (!isRecord(value)) return null;
		if (typeof value.number !== "number" || !Number.isInteger(value.number) || value.number <= 0) return null;
		if (typeof value.state !== "string" || !PR_STATES.has(value.state as PullRequestState)) return null;
		if (typeof value.isDraft !== "boolean") return null;

		const url = parsePullRequestUrl(value.url);
		if (!url) return null;

		return {
			number: value.number,
			url,
			state: value.state as PullRequestState,
			isDraft: value.isDraft,
		};
	} catch {
		return null;
	}
}

export async function lookupPullRequestStatus(
	pi: ExtensionAPI,
	cwd: string,
	signal?: AbortSignal,
): Promise<PullRequestStatus | null> {
	try {
		const result = await pi.exec("gh", ["pr", "view", "--json", "number,url,state,isDraft"], {
			cwd,
			timeout: PR_LOOKUP_TIMEOUT_MS,
			signal,
		});
		if (result.code !== 0) return null;
		return parsePullRequestStatus(result.stdout.trim());
	} catch {
		return null;
	}
}
