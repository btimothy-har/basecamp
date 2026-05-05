# Code Walkthrough — {{TARGET_LABEL}}

Please create a context-first code walkthrough review packet for {{TARGET_LABEL}}.

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

Start by calling `skill({ name: "code-walkthrough" })`, then follow that skill. Build the review packet and submit it with `review_packet`. If feedback includes `needs_code_change`, summarize it as review feedback only; do not edit code automatically.
