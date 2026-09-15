import { isAbsolute, relative, sep } from "node:path";

/** Normalize an in-repository absolute path while preserving other inputs. */
export function repositoryRelativePath(filePath: string, repositoryRoot: string | null): string {
	if (!repositoryRoot || !isAbsolute(filePath)) return filePath;
	const normalized = relative(repositoryRoot, filePath);
	if (normalized === "" || normalized === ".." || normalized.startsWith(`..${sep}`) || isAbsolute(normalized)) {
		return filePath;
	}
	return normalized.split(sep).join("/");
}
