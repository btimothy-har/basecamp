# Code Review — {{TARGET_LABEL}}

Please create a structured code review packet for {{TARGET_LABEL}}.

Context:
- Target label: {{TARGET_LABEL}}
- Branch: {{BRANCH}}
- Base branch: {{BASE}}
- Review packet target JSON:

```json
{{TARGET_JSON}}
```

Optional metadata command:

```bash
{{TARGET_CONTEXT_COMMANDS}}
```

Start by calling `skill({ name: "code-review" })`, then follow that skill. Build the review packet and submit it with `review_packet`. Do not paste inline diffs into the prompt; inspect repository state and diffs through tools as needed. If feedback includes `needs_code_change`, summarize it as review feedback only; do not edit code automatically.
