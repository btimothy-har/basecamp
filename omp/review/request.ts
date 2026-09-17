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

const REVIEW_PROCEDURE = `### Review protocol

1. Inspect only the scope above. For a committed scope, the repository and revisions are authoritative: exclude working-tree and index changes, and do not substitute current HEAD or \`read_diff\`. For a custom scope, follow the submitted instructions without widening them.
2. If the scope has no reviewable changes, report that and stop. Otherwise dispatch with \`task\` using \`agent: "reviewer"\`, passing the exact scope and user instructions. Split work only when the changed areas are independent.
3. Validate and present the reviewer results using the separately supplied chair instructions.
4. Review only. Do not edit code, create commits, or publish changes.`;

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
