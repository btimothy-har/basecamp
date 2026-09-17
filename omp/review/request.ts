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

const REVIEW_TRIGGER = "Read `skill://code-review`, then conduct a review using this context:";

function fencedText(text: string): string {
	const longestRun = Math.max(0, ...Array.from(text.matchAll(/`+/g), (match) => match[0].length));
	const fence = "`".repeat(Math.max(3, longestRun + 1));
	return `${fence}text\n${text}\n${fence}`;
}

function additionalInstructions(instructions: string | undefined): string {
	if (!instructions) return "";
	return `\n\nAdditional instructions:\n\n${fencedText(instructions)}`;
}

export function buildReviewRequest(scope: ReviewScope): string {
	if (scope.kind === "custom") {
		return `${REVIEW_TRIGGER}

- Scope: custom
- Invocation directory: ${JSON.stringify(scope.cwd)}

Review request:

${fencedText(scope.instructions)}`;
	}

	if (scope.kind === "branch") {
		return `${REVIEW_TRIGGER}

- Scope: committed branch comparison
- Repository: ${JSON.stringify(scope.repositoryRoot)}
- Selected base: ${JSON.stringify(scope.baseBranch)}
- Comparison base (merge base): ${scope.baseRevision}
- Head: ${JSON.stringify(scope.headLabel)}
- Head revision: ${scope.headRevision}
- Uncommitted changes: excluded${additionalInstructions(scope.instructions)}`;
	}

	return `${REVIEW_TRIGGER}

- Scope: specific commit
- Repository: ${JSON.stringify(scope.repositoryRoot)}
- Commit: ${scope.commitRevision}${additionalInstructions(scope.instructions)}`;
}
