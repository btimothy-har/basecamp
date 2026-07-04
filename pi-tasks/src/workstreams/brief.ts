export interface WorkstreamLaunchBriefSourceInput {
	dossierPath: string;
	repoPagePath?: string;
}

export interface WorkstreamLaunchBriefWorkstreamInput {
	label: string;
	brief: string;
	constraints?: string;
}

export interface WorkstreamLaunchBriefWorktreeInput {
	label: string;
	path: string;
	branch: string | null;
}

export interface WorkstreamLaunchBriefInput {
	source: WorkstreamLaunchBriefSourceInput;
	workstream: WorkstreamLaunchBriefWorkstreamInput;
	worktree: WorkstreamLaunchBriefWorktreeInput;
}

function metadataLines(input: WorkstreamLaunchBriefInput): string[] {
	return [`- Workstream label: ${input.workstream.label}`];
}

function sourceLines(input: WorkstreamLaunchBriefInput): string[] {
	return [
		`- Dossier: ${input.source.dossierPath}`,
		...(input.source.repoPagePath ? [`- Repo cockpit: ${input.source.repoPagePath}`] : []),
	];
}

export function buildWorkstreamLaunchBrief(input: WorkstreamLaunchBriefInput): string {
	const constraints = input.workstream.constraints?.trim();
	const contextReference = input.source.repoPagePath ? "the dossier and repo cockpit" : "the dossier";
	const sections = [
		[
			"# Herdr workstream launch brief",
			"",
			"You are the user-facing Herdr workstream surface for this launched workstream.",
		].join("\n"),
		["## Launch context", ...metadataLines(input)].join("\n"),
		[
			"## Assigned worktree",
			`- Worktree label: ${input.worktree.label}`,
			`- Worktree path: ${input.worktree.path}`,
			`- Branch: ${input.worktree.branch ?? "detached"}`,
			"",
			"Work only in the assigned worktree. Do not edit the protected checkout or any other worktree.",
		].join("\n"),
		[
			"## Source context",
			...sourceLines(input),
			"",
			`Read ${contextReference} as context when useful; you do not need to exhaustively reread them before every step.`,
		].join("\n"),
		["## Workstream brief", input.workstream.brief].join("\n"),
		...(constraints ? [["## Constraints", constraints].join("\n")] : []),
		[
			"## Operating guidance",
			"- Treat this brief as intentionally stretchable: when it is broad, decompose it, prioritize the most valuable path, and execute an appropriately sized slice; when it is specific, execute that agreed slice directly.",
			"- You may use subagents for smaller bounded tasks when that helps investigation, implementation, or review.",
			"- Do not write Logseq directly.",
			"- Do not push, create PRs, or merge unless explicitly asked.",
			"- Do not broadcast status outside this Herdr workstream; keep findings, changes, validation, and blocker context easy to summarize when asked.",
		].join("\n"),
	];

	return `${sections.join("\n\n")}\n`;
}
