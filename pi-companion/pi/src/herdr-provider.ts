import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import { canHostCompanionPane, type PaneProvider } from "./pane-provider.ts";

export interface HerdrPaneProviderInput {
	herdrEnv?: string;
	herdrPaneId?: string;
	herdrSocketPath?: string;
	hasUI: boolean;
	agentDepth: number;
}

const HERDR_PANE_ID_PATTERN = /^w[\w-]+:p[\w-]+$/;
const PANE_ID_KEYS = ["paneId", "pane_id", "id"] as const;

export function shouldCreateHerdrPane(input: HerdrPaneProviderInput): boolean {
	return (
		input.herdrEnv === "1" &&
		Boolean(input.herdrPaneId) &&
		Boolean(input.herdrSocketPath) &&
		canHostCompanionPane(input)
	);
}

export function buildHerdrSplitArgs(targetPaneId: string, cwd: string): string[] {
	return ["pane", "split", targetPaneId, "--direction", "right", "--cwd", cwd, "--no-focus", "--json"];
}

export function buildHerdrRunArgs(paneId: string, command: string): string[] {
	return ["pane", "run", paneId, command];
}

export function buildHerdrGetArgs(paneId: string): string[] {
	return ["pane", "get", paneId, "--json"];
}

export function buildHerdrCloseArgs(paneId: string): string[] {
	return ["pane", "close", paneId];
}

function isHerdrPaneId(value: unknown): value is string {
	return typeof value === "string" && HERDR_PANE_ID_PATTERN.test(value);
}

function extractPaneId(value: unknown): string | null {
	if (isHerdrPaneId(value)) return value;
	if (Array.isArray(value)) {
		for (const item of value) {
			const paneId = extractPaneId(item);
			if (paneId) return paneId;
		}
		return null;
	}
	if (!value || typeof value !== "object") return null;

	const record = value as Record<string, unknown>;
	for (const key of PANE_ID_KEYS) {
		const paneId = extractPaneId(record[key]);
		if (paneId) return paneId;
	}
	for (const item of Object.values(record)) {
		const paneId = extractPaneId(item);
		if (paneId) return paneId;
	}
	return null;
}

export function parseHerdrPaneId(stdout: string): string | null {
	const trimmed = stdout.trim();
	if (!trimmed) return null;
	try {
		return extractPaneId(JSON.parse(trimmed));
	} catch {
		return trimmed.match(/w[\w-]+:p[\w-]+/)?.[0] ?? null;
	}
}

async function closeHerdrPaneBestEffort(pi: ExtensionAPI, paneId: string): Promise<void> {
	try {
		await exec(pi, "herdr", buildHerdrCloseArgs(paneId));
	} catch {
		// best effort
	}
}

function resultError(action: string, code: number): Error {
	return new Error(`herdr pane ${action} failed with exit code ${code}`);
}

function createHerdrProvider(targetPaneId: string | null): PaneProvider {
	return {
		name: "herdr",
		async createPane(pi, input) {
			if (!targetPaneId) throw new Error("missing Herdr target pane");
			const splitResult = await exec(pi, "herdr", buildHerdrSplitArgs(targetPaneId, input.cwd));
			if (splitResult.code !== 0) throw resultError("split", splitResult.code);
			const paneId = parseHerdrPaneId(splitResult.stdout);
			if (!paneId) return null;
			try {
				const runResult = await exec(pi, "herdr", buildHerdrRunArgs(paneId, input.command));
				if (runResult.code !== 0) throw resultError("run", runResult.code);
				return paneId;
			} catch (err) {
				await closeHerdrPaneBestEffort(pi, paneId);
				throw err;
			}
		},
		async paneStillExists(pi, paneId) {
			try {
				const result = await exec(pi, "herdr", buildHerdrGetArgs(paneId));
				if (result.code !== 0) return false;
				const returnedPaneId = parseHerdrPaneId(result.stdout);
				return returnedPaneId ? returnedPaneId === paneId : true;
			} catch {
				return true;
			}
		},
		async closePane(pi, paneId) {
			await exec(pi, "herdr", buildHerdrCloseArgs(paneId));
		},
	};
}

export function createHerdrPaneProvider(input: HerdrPaneProviderInput): PaneProvider | null {
	if (!shouldCreateHerdrPane(input) || !input.herdrPaneId) return null;
	return createHerdrProvider(input.herdrPaneId);
}

export function createHerdrPaneCloser(): PaneProvider {
	return createHerdrProvider(null);
}
