function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

/** The `basecamp companion dashboard` command a pane runs, independent of pane backend. */
export function buildCompanionCommand(snapshotPath: string, cwd: string, scratchDir?: string): string {
	const base = `basecamp companion dashboard --snapshot ${shellQuote(snapshotPath)} --cwd ${shellQuote(cwd)}`;
	return scratchDir ? `${base} --scratch ${shellQuote(scratchDir)}` : base;
}
