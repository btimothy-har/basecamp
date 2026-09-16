import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { type as arktype } from "@oh-my-pi/omptype";
import type {
	AgentToolResult,
	ExtensionAPI,
	ExtensionContext,
	SessionEntry,
	ToolDefinition,
} from "@oh-my-pi/pi-coding-agent";
import registerAnnotationTools, { type AnnotateDiffInput, type RemoveAnnotationInput } from "../../annotation-tools.ts";
import { contentLines } from "../../annotations.ts";
import type { DiffFile, DiffSnapshot } from "../../loader.ts";

export const CONTENT = "one\ntwo\nthree\nfour\nfive\n";
export const NEW_LINES = new Map(contentLines(CONTENT).map((line, index) => [index + 1, line]));
const DIFF_FILES: DiffFile[] = [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }], newLines: NEW_LINES }];

const directories: string[] = [];

export function cleanupAnnotationToolHarnesses(): void {
	while (directories.length > 0) {
		const directory = directories.pop();
		if (directory) rmSync(directory, { recursive: true, force: true });
	}
}

export function repository(files: Record<string, string>): string {
	const root = mkdtempSync(path.join(tmpdir(), "basecamp-diff-tools-"));
	directories.push(root);
	for (const [name, content] of Object.entries(files)) {
		const full = path.join(root, name);
		mkdirSync(path.dirname(full), { recursive: true });
		writeFileSync(full, content);
	}
	return root;
}

export interface AppendedEntry {
	customType: string;
	data: unknown;
}

export interface AnnotationToolHarness {
	appended: AppendedEntry[];
	entries: SessionEntry[];
	annotate(input: AnnotateDiffInput, signal?: AbortSignal): Promise<AgentToolResult>;
	remove(input: RemoveAnnotationInput, signal?: AbortSignal): Promise<AgentToolResult>;
}

export function annotationToolHarness(options: {
	repositoryRoot: string;
	files?: DiffFile[];
	entries?: SessionEntry[];
	mode?: ExtensionContext["mode"];
	hasUI?: boolean;
	afterLoad?: () => void;
}): AnnotationToolHarness {
	const tools = new Map<string, ToolDefinition>();
	const appended: AppendedEntry[] = [];
	const snapshot: DiffSnapshot = {
		repositoryRoot: options.repositoryRoot,
		repository: "basecamp",
		defaultBranch: "main",
		baseRevision: "a".repeat(40),
		headRevision: "b".repeat(40),
		patch: "",
		files: options.files ?? DIFF_FILES,
	};
	const api = {
		arktype,
		registerTool(definition: ToolDefinition): void {
			tools.set(definition.name, definition);
		},
		appendEntry(customType: string, data?: unknown): void {
			appended.push({ customType, data });
		},
	} as unknown as ExtensionAPI;
	registerAnnotationTools(api, {
		loadDiff: async () => {
			options.afterLoad?.();
			return snapshot;
		},
	});
	const ctx = {
		cwd: options.repositoryRoot,
		mode: options.mode ?? "tui",
		hasUI: options.hasUI ?? true,
		sessionManager: { getBranch: () => options.entries ?? [] },
	} as unknown as ExtensionContext;

	function tool(name: string): ToolDefinition {
		const definition = tools.get(name);
		if (!definition) throw new Error(`${name} was not registered`);
		return definition;
	}

	return {
		appended,
		entries: options.entries ?? [],
		annotate: (input, signal) => tool("annotate_diff").execute("call-1", input, signal, undefined, ctx),
		remove: (input, signal) => tool("remove_annotation").execute("call-1", input, signal, undefined, ctx),
	};
}

export function journalEntries(appended: readonly AppendedEntry[]): SessionEntry[] {
	return appended.map(
		(record, index) =>
			({
				type: "custom",
				customType: record.customType,
				data: record.data,
				id: `entry-${index}`,
				parentId: index === 0 ? null : `entry-${index - 1}`,
				timestamp: "2026-09-16T00:00:00.000Z",
			}) as SessionEntry,
	);
}

export function annotationInput(
	annotations: Partial<AnnotateDiffInput["annotations"][number]>[] = [{}],
): AnnotateDiffInput {
	return {
		annotations: annotations.map((overrides) => ({
			path: "src/a.ts",
			line_start: 2,
			line_end: 4,
			summary: "watch this",
			...overrides,
		})),
	};
}
