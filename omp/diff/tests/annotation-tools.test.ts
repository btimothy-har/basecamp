import { afterEach, describe, expect, test } from "bun:test";
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
import registerAnnotationTools, {
	type AnnotateDiffDetails,
	type AnnotateDiffInput,
	type RemoveAnnotationDetails,
	type RemoveAnnotationInput,
} from "../annotation-tools.ts";
import { anchorHash, annotationId, contentLines } from "../annotations.ts";
import { activeAnnotations, DIFF_ANNOTATION_CUSTOM_TYPE, parseDiffJournalEvent } from "../journal.ts";
import type { DiffFile, DiffSnapshot } from "../loader.ts";

const CONTENT = "one\ntwo\nthree\nfour\nfive\n";
const NEW_LINES = new Map(contentLines(CONTENT).map((line, index) => [index + 1, line]));
const DIFF_FILES: DiffFile[] = [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }], newLines: NEW_LINES }];

const directories: string[] = [];

afterEach(() => {
	while (directories.length > 0) {
		const directory = directories.pop();
		if (directory) rmSync(directory, { recursive: true, force: true });
	}
});

function repository(files: Record<string, string>): string {
	const root = mkdtempSync(path.join(tmpdir(), "basecamp-diff-tools-"));
	directories.push(root);
	for (const [name, content] of Object.entries(files)) {
		const full = path.join(root, name);
		mkdirSync(path.dirname(full), { recursive: true });
		writeFileSync(full, content);
	}
	return root;
}

interface AppendedEntry {
	customType: string;
	data: unknown;
}

interface Harness {
	appended: AppendedEntry[];
	entries: SessionEntry[];
	annotate(input: AnnotateDiffInput): Promise<AgentToolResult>;
	remove(input: RemoveAnnotationInput): Promise<AgentToolResult>;
}

function harness(options: {
	repositoryRoot: string;
	files?: DiffFile[];
	entries?: SessionEntry[];
	mode?: ExtensionContext["mode"];
	hasUI?: boolean;
}): Harness {
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
	registerAnnotationTools(api, { loadDiff: async () => snapshot });
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
		annotate: (input) => tool("annotate_diff").execute("call-1", input, undefined, undefined, ctx),
		remove: (input) => tool("remove_annotation").execute("call-1", input, undefined, undefined, ctx),
	};
}

/** Turn a harness's appended events into branch entries for the next harness. */
function journalEntries(appended: readonly AppendedEntry[]): SessionEntry[] {
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

function input(annotations: Partial<AnnotateDiffInput["annotations"][number]>[] = [{}]): AnnotateDiffInput {
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

describe("annotate_diff", () => {
	test("records one journal event with full payloads and returns stable ids", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		const result = await h.annotate(input());

		expect(h.appended).toHaveLength(1);
		expect(h.appended[0]?.customType).toBe(DIFF_ANNOTATION_CUSTOM_TYPE);
		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		const recorded = event.annotations[0];
		if (!recorded) throw new Error("expected one recorded annotation");
		const expectedAnchorHash = anchorHash("src/a.ts", { start: 2, end: 4 }, CONTENT);
		if (expectedAnchorHash === null) throw new Error("expected a valid anchor hash");
		expect(recorded).toEqual({
			id: annotationId({
				repository: "basecamp",
				path: "src/a.ts",
				newRange: { start: 2, end: 4 },
				summary: "watch this",
			}),
			repository: "basecamp",
			path: "src/a.ts",
			newRange: { start: 2, end: 4 },
			anchorHash: expectedAnchorHash,
			summary: "watch this",
		});
		// details comes from our own tool definition above, not external input.
		const details = result.details as AnnotateDiffDetails;
		expect(details.recorded).toHaveLength(1);
		expect(details.active).toBe(1);
		const text = result.content[0]?.type === "text" ? result.content[0].text : "";
		expect(text).toContain(recorded.id);
	});

	test("threads rationale through to the recorded annotation", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await h.annotate(input([{ rationale: "boundary math lives here" }]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations[0]?.rationale).toBe("boundary math lives here");
	});

	test("rebases an in-repository absolute path", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await h.annotate(input([{ path: path.join(root, "src/a.ts") }]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations[0]?.path).toBe("src/a.ts");
	});

	test("rejects invalid targets and appends nothing", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await expect(h.annotate(input([{ path: "../outside.ts" }, {}]))).rejects.toThrow(/rejected/);
		expect(h.appended).toHaveLength(0);
	});

	test("rejects ranges outside the displayed new-side hunk lines", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({
			repositoryRoot: root,
			files: [{ path: "src/a.ts", newRanges: [{ start: 1, end: 3 }], newLines: NEW_LINES }],
		});

		await expect(h.annotate(input([{ line_start: 4, line_end: 5 }]))).rejects.toThrow(
			/outside the displayed new-side hunk lines/,
		);
		expect(h.appended).toHaveLength(0);
	});

	test("collapses exact duplicates within one batch", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		const result = await h.annotate(input([{}, {}]));

		const event = parseDiffJournalEvent(h.appended[0]?.data);
		if (event?.kind !== "recorded") throw new Error("expected a recorded event");
		expect(event.annotations).toHaveLength(1);
		const details = result.details as AnnotateDiffDetails;
		expect(details.skippedDuplicates).toBe(1);
	});

	test("exact duplicates of active annotations no-op without an event", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		await first.annotate(input());

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		const result = await second.annotate(input());

		expect(second.appended).toHaveLength(0);
		const text = result.content[0]?.type === "text" ? result.content[0].text : "";
		expect(text).toMatch(/No new annotations/);
		const details = result.details as AnnotateDiffDetails;
		expect(details.active).toBe(1);
	});

	test("a reworded rationale records a new annotation under a new id", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		await first.annotate(input());

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		await second.annotate(input([{ rationale: "corrected" }]));

		expect(second.appended).toHaveLength(1);
		expect(activeAnnotations([...second.entries, ...journalEntries(second.appended)])).toHaveLength(2);
	});

	test("is only available to the interactive session that owns /diff", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		for (const options of [
			{ mode: "print" as const },
			{ mode: "rpc" as const },
			{ mode: "tui" as const, hasUI: false },
		]) {
			const h = harness({ repositoryRoot: root, ...options });
			await expect(h.annotate(input())).rejects.toThrow(/only available in the interactive session/);
			expect(h.appended).toHaveLength(0);
		}
	});
});

/** details is this module's own tool payload, not external input. */
function recordedId(result: AgentToolResult): string {
	const details = result.details as AnnotateDiffDetails;
	const id = details.recorded[0]?.id;
	if (!id) throw new Error("expected a recorded id");
	return id;
}

describe("remove_annotation", () => {
	test("appends a withdrawal for currently active ids", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		const removal = await second.remove({ ids: [id] });

		expect(second.appended).toHaveLength(1);
		expect(parseDiffJournalEvent(second.appended[0]?.data)).toEqual({ v: 1, kind: "withdrawn", ids: [id] });
		const details = removal.details as RemoveAnnotationDetails;
		expect(details.withdrawn).toEqual([id]);
		expect(activeAnnotations([...second.entries, ...journalEntries(second.appended)])).toEqual([]);
	});

	test("dedupes repeated ids in one call", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));

		const second = harness({ repositoryRoot: root, entries: journalEntries(first.appended) });
		await second.remove({ ids: [id, id] });

		expect(parseDiffJournalEvent(second.appended[0]?.data)).toEqual({ v: 1, kind: "withdrawn", ids: [id] });
	});

	test("rejects ids without an active annotation and appends nothing", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const h = harness({ repositoryRoot: root });

		await expect(h.remove({ ids: ["000000000000"] })).rejects.toThrow(/No active annotation with id/);
		expect(h.appended).toHaveLength(0);
	});

	test("a completed /diff clears the ids a withdrawal can target", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const first = harness({ repositoryRoot: root });
		const id = recordedId(await first.annotate(input()));
		const completedBoundary = journalEntries([
			...first.appended,
			{
				customType: DIFF_ANNOTATION_CUSTOM_TYPE,
				data: { v: 1, kind: "diff-completed", reviewRef: "artifact://r1", throughEntryId: "entry-0" },
			},
		]);

		const second = harness({ repositoryRoot: root, entries: completedBoundary });
		await expect(second.remove({ ids: [id] })).rejects.toThrow(/No active annotation with id/);
		expect(second.appended).toHaveLength(0);
	});

	test("is only available to the interactive session that owns /diff", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		for (const options of [{ mode: "json" as const }, { mode: "tui" as const, hasUI: false }]) {
			const h = harness({ repositoryRoot: root, ...options });
			await expect(h.remove({ ids: ["000000000000"] })).rejects.toThrow(/only available in the interactive session/);
			expect(h.appended).toHaveLength(0);
		}
	});
});
