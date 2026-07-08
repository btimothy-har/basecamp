import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export interface WorktreeSetupOptions {
	command: string;
	worktreeDir: string;
	repoRoot: string;
	timeoutMs?: number;
}

export interface WorktreeSetupResult {
	ran: boolean;
	exitCode: number;
	timedOut: boolean;
	stderrTail: string;
}

export function shouldRunWorktreeSetup(created: boolean, command: string | null): boolean {
	return created && command !== null;
}

function tail(value: string): string {
	return value.length > 2000 ? value.slice(-2000) : value;
}

export async function runWorktreeSetup(pi: ExtensionAPI, opts: WorktreeSetupOptions): Promise<WorktreeSetupResult> {
	const timeoutMs = opts.timeoutMs ?? 180_000;
	const prev = process.env.BASECAMP_REPO_ROOT;
	process.env.BASECAMP_REPO_ROOT = opts.repoRoot;
	try {
		const result = await pi.exec("bash", ["-lc", opts.command], {
			cwd: opts.worktreeDir,
			timeout: timeoutMs,
		});
		return {
			ran: true,
			exitCode: result.code,
			timedOut: result.killed === true,
			stderrTail: tail(result.stderr),
		};
	} finally {
		if (prev === undefined) {
			delete process.env.BASECAMP_REPO_ROOT;
		} else {
			process.env.BASECAMP_REPO_ROOT = prev;
		}
	}
}
