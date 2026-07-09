# git

Basecamp git workflow context for prompt-only pull request creation.

## What it does

- **`/create-pr` command**: sends a prompt instructing the agent to create or update a pull request directly with bash/`gh` commands, including checking for an existing PR, pushing the branch if needed, and summarizing the result.

## Dependencies

- **core** (`#core/*`): exec wrapper used to resolve the default base branch for the PR prompt.
