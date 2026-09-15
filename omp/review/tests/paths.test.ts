import { afterEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findRepositoryRoot, repositoryRelativePath } from "../paths.ts";

const temporaryRoots: string[] = [];

afterEach(async () => {
	await Promise.all(temporaryRoots.splice(0).map((root) => rm(root, { force: true, recursive: true })));
});

async function temporaryRoot(): Promise<string> {
	const root = await mkdtemp(join(tmpdir(), "basecamp-review-paths-"));
	temporaryRoots.push(root);
	return root;
}

describe("review finding paths", () => {
	test("finds a worktree root from a nested working directory", async () => {
		const root = await temporaryRoot();
		const repository = join(root, "repository");
		const nested = join(repository, "omp", "review");
		await mkdir(nested, { recursive: true });
		await writeFile(join(repository, ".git"), "gitdir: /tmp/example\n");

		expect(await findRepositoryRoot(nested)).toBe(repository);
		expect(repositoryRelativePath(join(repository, "pi", "extension.ts"), repository)).toBe("pi/extension.ts");
	});

	test("preserves relative and out-of-repository paths", async () => {
		const root = await temporaryRoot();
		const repository = join(root, "repository");
		await mkdir(join(repository, ".git"), { recursive: true });

		expect(repositoryRelativePath("omp/review/tool.ts", repository)).toBe("omp/review/tool.ts");
		expect(repositoryRelativePath(join(root, "other", "file.ts"), repository)).toBe(join(root, "other", "file.ts"));
	});

	test("returns null when no repository marker exists", async () => {
		const root = await temporaryRoot();
		const nested = join(root, "plain", "nested");
		await mkdir(nested, { recursive: true });

		expect(await findRepositoryRoot(nested)).toBeNull();
	});
});
