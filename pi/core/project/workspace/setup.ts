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
	// The hook sees BASECAMP_REPO_ROOT via env(1) rather than a process.env mutation: setup
	// now runs concurrently (one per dispatch), and a shared global would race — vanishing
	// mid-hook or leaking into a concurrent child's persistent environment.
	const result = await pi.exec("env", [`BASECAMP_REPO_ROOT=${opts.repoRoot}`, "bash", "-lc", opts.command], {
		cwd: opts.worktreeDir,
		timeout: timeoutMs,
	});
	return {
		ran: true,
		exitCode: result.code,
		timedOut: result.killed === true,
		stderrTail: tail(result.stderr),
	};
}
