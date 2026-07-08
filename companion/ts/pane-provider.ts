import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export type PaneProviderName = "tmux" | "herdr";

export interface PaneProviderCreateInput {
	cwd: string;
	command: string;
}

export interface PaneProvider {
	readonly name: PaneProviderName;
	createPane(pi: ExtensionAPI, input: PaneProviderCreateInput): Promise<string | null>;
	paneStillExists(pi: ExtensionAPI, paneId: string): Promise<boolean>;
	closePane(pi: ExtensionAPI, paneId: string): Promise<void>;
}

export interface PaneProviderSelectionInput {
	hasUI: boolean;
	agentDepth: number;
}

export function canHostCompanionPane(input: PaneProviderSelectionInput): boolean {
	return input.hasUI && input.agentDepth === 0;
}
