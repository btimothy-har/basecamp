import { afterEach, describe, expect, test } from "bun:test";
import {
	lstatSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	readlinkSync,
	rmSync,
	symlinkSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import type { DiffAnnotation } from "../annotations.ts";
import { anchorHash, annotationId, contentLines } from "../annotations.ts";
import type { DiffFile, DiffSnapshot } from "../loader.ts";
import type { AnnotationTarget } from "../validate.ts";
import { repositoryRelativePath, revalidateAnnotations, validateTargets } from "../validate.ts";

const directories: string[] = [];

afterEach(() => {
	while (directories.length > 0) {
		const directory = directories.pop();
		if (directory) rmSync(directory, { recursive: true, force: true });
	}
});

const CONTENT = "one\ntwo\nthree\nfour\nfive\n";

function repository(files: Record<string, string>): string {
	const root = mkdtempSync(path.join(tmpdir(), "basecamp-diff-validate-"));
	directories.push(root);
	for (const [name, content] of Object.entries(files)) {
		const full = path.join(root, name);
		mkdirSync(path.dirname(full), { recursive: true });
		writeFileSync(full, content);
	}
	return root;
}

type DiffFileInput = Omit<DiffFile, "newLines"> & { newLines?: ReadonlyMap<number, string> };

function frozenLines(repositoryRoot: string, file: DiffFileInput): ReadonlyMap<number, string> {
	if (file.newLines) return file.newLines;
	const lines = new Map<number, string>();
	try {
		const filePath = path.join(repositoryRoot, file.path);
		const metadata = lstatSync(filePath);
		const content = metadata.isSymbolicLink() ? readlinkSync(filePath) : readFileSync(filePath, "utf8");
		const source = contentLines(content);
		for (const range of file.newRanges) {
			for (let line = range.start; line <= range.end; line++) {
				const text = source[line - 1];
				if (text !== undefined) lines.set(line, text);
			}
		}
	} catch {
		// A missing line stays absent from the synthetic frozen snapshot.
	}
	return lines;
}

function snapshot(repositoryRoot: string, files: DiffFileInput[]): DiffSnapshot {
	return {
		repositoryRoot,
		repository: "basecamp",
		defaultBranch: "main",
		baseRevision: "a".repeat(40),
		headRevision: "b".repeat(40),
		patch: "",
		files: files.map((file) => ({ ...file, newLines: frozenLines(repositoryRoot, file) })),
	};
}

function target(overrides: Partial<AnnotationTarget> = {}): AnnotationTarget {
	return { path: "src/a.ts", range: { start: 2, end: 4 }, summary: "watch this", ...overrides };
}

function activeAnnotation(root: string, file: string, range: { start: number; end: number }): DiffAnnotation {
	const content = readFileSync(path.join(root, file), "utf8");
	const hash = anchorHash(file, range, content);
	if (hash === null) throw new Error("fixture range does not address content");
	return {
		id: annotationId({ repository: "basecamp", path: file, newRange: range, summary: "watch this" }),
		repository: "basecamp",
		path: file,
		newRange: range,
		anchorHash: hash,
		summary: "watch this",
	};
}

describe("repositoryRelativePath", () => {
	test("normalizes relative and in-repository absolute paths", () => {
		expect(repositoryRelativePath("src/a.ts", "/repo")).toBe("src/a.ts");
		expect(repositoryRelativePath("./src/a.ts", "/repo")).toBe("src/a.ts");
		expect(repositoryRelativePath("src//a.ts", "/repo")).toBe("src/a.ts");
		expect(repositoryRelativePath("/repo/src/a.ts", "/repo")).toBe("src/a.ts");
	});

	test("rejects paths outside the repository", () => {
		expect(repositoryRelativePath("../outside.ts", "/repo")).toBeNull();
		expect(repositoryRelativePath("src/../../outside.ts", "/repo")).toBeNull();
		expect(repositoryRelativePath("/elsewhere/a.ts", "/repo")).toBeNull();
		expect(repositoryRelativePath("", "/repo")).toBeNull();
		expect(repositoryRelativePath(".", "/repo")).toBeNull();
		expect(repositoryRelativePath("/repo", "/repo")).toBeNull();
	});
});

describe("validateTargets", () => {
	test("accepts a target contained in a displayed new-side hunk range and hashes its lines", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [
			{
				path: "src/a.ts",
				newRanges: [
					{ start: 1, end: 3 },
					{ start: 5, end: 5 },
				],
			},
		]);

		const result = await validateTargets(snap, [target({ range: { start: 2, end: 3 } })]);

		const expectedAnchorHash = anchorHash("src/a.ts", { start: 2, end: 3 }, CONTENT);
		if (expectedAnchorHash === null) throw new Error("expected a valid anchor hash");
		expect(result.issues).toEqual([]);
		expect(result.valid).toEqual([
			{
				path: "src/a.ts",
				newRange: { start: 2, end: 3 },
				anchorHash: expectedAnchorHash,
				summary: "watch this",
			},
		]);
	});

	test("rebases an in-repository absolute path", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const result = await validateTargets(snap, [target({ path: path.join(root, "src/a.ts") })]);

		expect(result.issues).toEqual([]);
		expect(result.valid[0]?.path).toBe("src/a.ts");
	});

	test("rejects paths outside the repository", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const result = await validateTargets(snap, [target({ path: "../outside.ts" })]);

		expect(result.valid).toEqual([]);
		expect(result.issues[0]?.reason).toMatch(/outside the repository/);
	});

	test("rejects non-1-based and reversed ranges", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const zero = await validateTargets(snap, [target({ range: { start: 0, end: 2 } })]);
		const reversed = await validateTargets(snap, [target({ range: { start: 4, end: 2 } })]);

		expect(zero.issues[0]?.reason).toMatch(/1-based/);
		expect(reversed.issues[0]?.reason).toMatch(/reversed/);
		expect(zero.valid).toEqual([]);
		expect(reversed.valid).toEqual([]);
	});

	test("rejects a file that is not part of the current diff", async () => {
		const root = repository({ "src/a.ts": CONTENT, "src/other.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const result = await validateTargets(snap, [target({ path: "src/other.ts" })]);

		expect(result.valid).toEqual([]);
		expect(result.issues[0]?.reason).toMatch(/not part of the current diff/);
	});

	test("rejects ranges not contained in one displayed hunk, including spans across hunks", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [
			{
				path: "src/a.ts",
				newRanges: [
					{ start: 1, end: 3 },
					{ start: 5, end: 5 },
				],
			},
		]);

		const spanning = await validateTargets(snap, [target({ range: { start: 3, end: 5 } })]);
		const inside = await validateTargets(snap, [target({ range: { start: 5, end: 5 } })]);

		expect(spanning.valid).toEqual([]);
		expect(spanning.issues[0]?.reason).toMatch(/outside the displayed new-side hunk lines \(1-3, 5\)/);
		expect(inside.issues).toEqual([]);
	});

	test("rejects ranges past end of file and unreadable files", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [
			{ path: "src/a.ts", newRanges: [{ start: 1, end: 10 }] },
			{ path: "src/gone.ts", newRanges: [{ start: 1, end: 2 }] },
		]);

		const pastEnd = await validateTargets(snap, [target({ range: { start: 1, end: 6 } })]);
		const unreadable = await validateTargets(snap, [target({ path: "src/gone.ts", range: { start: 1, end: 2 } })]);

		expect(pastEnd.issues[0]?.reason).toMatch(/does not address the frozen diff content/);
		expect(unreadable.issues[0]?.reason).toMatch(/does not address the frozen diff content/);
	});

	test("keeps valid siblings when other targets are rejected", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const result = await validateTargets(snap, [target(), target({ path: "../outside.ts" })]);

		expect(result.valid).toHaveLength(1);
		expect(result.issues).toHaveLength(1);
	});

	test("hashes a symlink's Git link text and detects retargeting", async () => {
		const root = repository({});
		const linkPath = path.join(root, "src/link.ts");
		mkdirSync(path.dirname(linkPath), { recursive: true });
		symlinkSync("missing-a.ts", linkPath);
		const snap = snapshot(root, [{ path: "src/link.ts", newRanges: [{ start: 1, end: 1 }] }]);

		const validated = await validateTargets(snap, [target({ path: "src/link.ts", range: { start: 1, end: 1 } })]);
		const expectedHash = anchorHash("src/link.ts", { start: 1, end: 1 }, "missing-a.ts");
		if (expectedHash === null) throw new Error("expected link text to produce an anchor hash");
		expect(validated.valid[0]?.anchorHash).toBe(expectedHash);

		const current = {
			...validated.valid[0],
			id: "symlink-annotation",
			repository: "basecamp",
		} as DiffAnnotation;
		rmSync(linkPath);
		symlinkSync("missing-b.ts", linkPath);
		const retargeted = snapshot(root, [{ path: "src/link.ts", newRanges: [{ start: 1, end: 1 }] }]);
		expect(await revalidateAnnotations(retargeted, [current])).toEqual({ current: [], stale: [current] });
	});
});

describe("revalidateAnnotations", () => {
	test("keeps annotations whose anchor still matches", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);
		const annotation = activeAnnotation(root, "src/a.ts", { start: 2, end: 4 });

		const result = await revalidateAnnotations(snap, [annotation]);

		expect(result).toEqual({ current: [annotation], stale: [] });
	});

	test("stays anchored to a frozen snapshot and becomes stale in the next load", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);
		const annotation = activeAnnotation(root, "src/a.ts", { start: 2, end: 4 });
		writeFileSync(path.join(root, "src/a.ts"), "one\nTWO\nthree\nfour\nfive\n");

		expect(await revalidateAnnotations(snap, [annotation])).toEqual({ current: [annotation], stale: [] });

		const nextSnap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);
		expect(await revalidateAnnotations(nextSnap, [annotation])).toEqual({ current: [], stale: [annotation] });
	});

	test("discards annotations whose file or range left the displayed diff", async () => {
		const root = repository({ "src/a.ts": CONTENT, "src/b.ts": CONTENT });
		const inDiff = activeAnnotation(root, "src/a.ts", { start: 2, end: 4 });
		const leftDiff = activeAnnotation(root, "src/b.ts", { start: 2, end: 4 });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 4, end: 5 }] }]);

		const result = await revalidateAnnotations(snap, [inDiff, leftDiff]);

		expect(result.current).toEqual([]);
		expect(result.stale).toEqual([inDiff, leftDiff]);
	});

	test("preserves the recorded order across different stale reasons", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);
		const changed = { ...activeAnnotation(root, "src/a.ts", { start: 2, end: 4 }), anchorHash: "changed" };
		const foreign = { ...activeAnnotation(root, "src/a.ts", { start: 1, end: 2 }), repository: "other" };

		const result = await revalidateAnnotations(snap, [changed, foreign]);

		expect(result).toEqual({ current: [], stale: [changed, foreign] });
	});
	test("discards annotations from another repository without reading the file", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);
		const annotation = { ...activeAnnotation(root, "src/a.ts", { start: 2, end: 4 }), repository: "other" };

		const result = await revalidateAnnotations(snap, [annotation]);

		expect(result).toEqual({ current: [], stale: [annotation] });
	});

	test("discards annotations whose file is absent from the next snapshot", async () => {
		const root = repository({ "src/a.ts": CONTENT });
		const annotation = activeAnnotation(root, "src/a.ts", { start: 2, end: 4 });
		rmSync(path.join(root, "src/a.ts"));
		const snap = snapshot(root, [{ path: "src/a.ts", newRanges: [{ start: 1, end: 5 }] }]);

		const result = await revalidateAnnotations(snap, [annotation]);

		expect(result).toEqual({ current: [], stale: [annotation] });
	});
});
