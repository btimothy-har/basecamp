import { stat } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

async function hasGitMarker(directory: string): Promise<boolean> {
	try {
		await stat(join(directory, ".git"));
		return true;
	} catch (error) {
		if (
			typeof error === "object" &&
			error !== null &&
			"code" in error &&
			(error.code === "ENOENT" || error.code === "ENOTDIR")
		) {
			return false;
		}
		throw error;
	}
}

/** Find the nearest repository or worktree root containing a `.git` marker. */
export async function findRepositoryRoot(cwd: string): Promise<string | null> {
	let directory = resolve(cwd);
	while (true) {
		if (await hasGitMarker(directory)) return directory;
		const parent = dirname(directory);
		if (parent === directory) return null;
		directory = parent;
	}
}

/** Normalize an in-repository absolute path while preserving other inputs. */
export function repositoryRelativePath(filePath: string, repositoryRoot: string | null): string {
	if (!repositoryRoot || !isAbsolute(filePath)) return filePath;
	const normalized = relative(repositoryRoot, filePath);
	if (normalized === "" || normalized === ".." || normalized.startsWith(`..${sep}`) || isAbsolute(normalized)) {
		return filePath;
	}
	return normalized.split(sep).join("/");
}
