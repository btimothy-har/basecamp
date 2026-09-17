import { $ } from "bun";

export type ReviewScope =
	| {
			kind: "branch";
			repositoryRoot: string;
			baseBranch: string;
			headLabel: string;
			baseRevision: string;
			headRevision: string;
			instructions?: string;
	  }
	| {
			kind: "commit";
			repositoryRoot: string;
			commitRevision: string;
			instructions?: string;
	  }
	| {
			kind: "custom";
			cwd: string;
			instructions: string;
	  };

const REVIEW_PROCEDURE = `### Procedure

1. Inspect the selected scope before dispatch. For a committed scope, the supplied repository and exact revisions are authoritative. Do not substitute current HEAD, working-tree or index changes, or \`read_diff\`. For a custom scope, resolve the submitted instructions using available tools; preserve an explicitly requested branch refinement instead of widening it to a generic workspace review.
2. Use Git and tool output to identify the relevant changed files and material areas. Do not discard files through a hardcoded extension list. Identify generated or binary coverage that cannot be reviewed meaningfully instead of silently claiming it was reviewed.
3. Use the \`task\` tool with \`agent: "reviewer"\` and a \`tasks\` array. Use one reviewer for a small coherent scope and independent reviewers in parallel when the material areas warrant it. Give every reviewer the exact scope, repository, and user instructions.
4. Reviewers return findings and verdicts through their native structured yield and never call \`review_findings\`. Follow the separately supplied presentation instructions for primary validation and consolidation.
5. If inspection finds no relevant changes, explain that result without dispatching meaningless reviewer tasks. Do not switch modes or silently widen the scope.
6. This workflow is review-only. Do not edit code, create commits, or publish changes. Implementing fixes requires an explicit user request.`;

function fencedText(text: string): string {
	const longestRun = Math.max(0, ...Array.from(text.matchAll(/`+/g), (match) => match[0].length));
	const fence = "`".repeat(Math.max(3, longestRun + 1));
	return `${fence}text\n${text}\n${fence}`;
}

function userInstructions(instructions: string | undefined): string {
	if (!instructions) return "";
	return `\n\n### User instructions\n\n${fencedText(instructions)}`;
}

function committedInspectionGuidance(command: string): string {
	return `### Inspect the committed scope

Run this exact comparison first:

\`\`\`sh
${command}
\`\`\`

For file-restricted inspection, add the assigned repository-relative paths after \`--\`. Read committed source context with \`git show <revision>:<path>\` rather than potentially dirty working-tree files.`;
}

export function buildReviewRequest(scope: ReviewScope): string {
	if (scope.kind === "custom") {
		return `## Code Review Request

### Scope

- Mode: custom instructions
- Invocation cwd: ${JSON.stringify(scope.cwd)}

### Submitted instructions

${fencedText(scope.instructions)}

${REVIEW_PROCEDURE}`;
	}

	if (scope.kind === "branch") {
		const command = [
			"git -C",
			$.escape(scope.repositoryRoot),
			"diff",
			$.escape(scope.baseRevision),
			$.escape(scope.headRevision),
			"--",
		].join(" ");
		return `## Code Review Request

### Scope

- Mode: branch comparison
- Repository: ${JSON.stringify(scope.repositoryRoot)}
- Selected base: ${JSON.stringify(scope.baseBranch)}
- Head: ${JSON.stringify(scope.headLabel)}
- Base revision (merge base): ${scope.baseRevision}
- Head revision: ${scope.headRevision}${userInstructions(scope.instructions)}

${committedInspectionGuidance(command)}

${REVIEW_PROCEDURE}`;
	}

	const command = [
		"git -C",
		$.escape(scope.repositoryRoot),
		"show",
		"--format=fuller",
		"--patch",
		$.escape(scope.commitRevision),
		"--",
	].join(" ");
	return `## Code Review Request

### Scope

- Mode: specific commit
- Repository: ${JSON.stringify(scope.repositoryRoot)}
- Commit revision: ${scope.commitRevision}${userInstructions(scope.instructions)}

${committedInspectionGuidance(command)}

${REVIEW_PROCEDURE}`;
}
