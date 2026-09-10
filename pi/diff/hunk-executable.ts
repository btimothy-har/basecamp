import { constants } from "node:fs";
import { access, stat } from "node:fs/promises";
import { delimiter, resolve } from "node:path";

export async function resolveHunkExecutable(path: string | undefined, cwd: string): Promise<string | null> {
	if (path === undefined) return null;
	for (const directory of path.split(delimiter)) {
		const candidate = resolve(cwd, directory, "hunk");
		try {
			if (!(await stat(candidate)).isFile()) continue;
			await access(candidate, constants.X_OK);
			// Preserve the PATH pathname: resolving a launcher symlink can change its behavior.
			return candidate;
		} catch {
			// Missing or inaccessible candidates do not shadow later executable PATH entries.
		}
	}
	return null;
}
