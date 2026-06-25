# pi-bash-reviewer

Basecamp bash reviewer — LLM gate for risky git/gh/shell commands.

## What it does

- **Bash reviewer hook**: registers a `tool_call` hook for `bash`
- **Reviewer runtime**: intended to host the LLM gate for risky git/gh/shell commands

## Dependencies

- **pi-core** (hard peer dep): shared Basecamp/Pi runtime primitives
- **@earendil-works/pi-ai**: model API used by the reviewer

## Installation

```bash
pi install /path/to/pi-bash-reviewer
```

Installed automatically by `install.py`.
