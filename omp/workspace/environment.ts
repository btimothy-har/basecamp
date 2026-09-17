import * as path from "node:path";

export const PROTECTED_ROOT_ENV = "BASECAMP_PROTECTED_ROOT";
export const SCRATCH_ROOT_ENV = "BASECAMP_OMP_SCRATCH_ROOT";
export const INHERITED_WIP_ENV = "BASECAMP_OMP_INHERITED_WIP";

export interface WorkspaceEnvironment {
	protectedRoot: string | null;
	scratchRoot: string | null;
	inheritedWip: boolean | null;
}

export function readWorkspaceEnvironment(env: NodeJS.ProcessEnv = process.env): WorkspaceEnvironment {
	const protectedRoot = absolutePath(env[PROTECTED_ROOT_ENV]);
	const scratchRoot = absolutePath(env[SCRATCH_ROOT_ENV]);
	const inherited = env[INHERITED_WIP_ENV];
	const inheritedWip = inherited === "1" ? true : inherited === "0" ? false : null;
	if (!protectedRoot || !scratchRoot || inheritedWip === null) {
		return { protectedRoot, scratchRoot: null, inheritedWip: null };
	}
	return { protectedRoot, scratchRoot, inheritedWip };
}

function absolutePath(value: string | undefined): string | null {
	return value && path.isAbsolute(value) ? path.normalize(value) : null;
}
