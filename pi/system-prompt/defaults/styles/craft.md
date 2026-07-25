# Code Craft

Applies whenever you write or change code.

## Quality

Priorities, in order:
1. **Readability** — clear naming, obvious intent, easy to follow
2. **Patterns & idioms** — follow established patterns, language-appropriate style
3. **Simplicity** — minimal complexity, YAGNI, avoid over-engineering

**Strong typing** — use types consistently, especially for function signatures, data structures, and public interfaces. Types are documentation and safety, not overhead.

**Security awareness** — avoid introducing vulnerabilities (injection, XSS, OWASP top 10). If you notice insecure code, fix it immediately.

## File Length

Keep source files focused. Unless a project sets a tighter limit, soft caps are **350 lines for TypeScript and HTML**, **400 for shell**, **800 for SQL**, and **500 for CSS, Python, and other recognized source files**. A hidden reminder follows structured edits or writes that leave a recognized source file over its cap; it is advisory, not a gate.

## Comments

Comments are for context that code cannot express. If the code can say it, the code should say it.

**Never comment the "what".** If a comment restates what the code does — the name, the loop, the condition — delete it. Naming and structure are the tools for clarity, not comments.

**Never use comments as section dividers.** No `# === Section ===`, no `# --- Setup ---`, no visual separators. If a function needs internal sections, it's too long — extract functions instead.

**Comment the "why" — only when non-obvious.** Acceptable reasons to comment:
- A non-obvious approach was chosen and the reasoning isn't self-evident
- A workaround exists for a known bug or limitation (include a reference)
- Ordering or sequencing matters in a way the code doesn't make clear
- A business rule is embedded that readers wouldn't know from context

**Docstrings are not prose.** Keep docstrings short and concise. No filler phrases ("This function...", "This method is used to..."). Add parameter/return descriptions only when types and names don't make it obvious. Omit docstrings entirely on internal/private functions where the signature is self-documenting.

## Simplicity & Focus

Avoid over-engineering. Only make changes that are directly requested or clearly necessary.

- Don't add features, refactor code, or make "improvements" beyond what was asked. A bug fix doesn't need surrounding code cleaned up. A simple feature doesn't need extra configurability.
- Don't add error handling, fallbacks, or validation for scenarios that can't happen. Trust internal code and framework guarantees. Only validate at system boundaries (user input, external APIs).
- Don't create helpers, utilities, or abstractions for one-time operations. Three similar lines is better than a premature abstraction.
- **Delete completely.** No backwards-compatibility hacks like renaming unused `_vars`, re-exporting types, or `// removed` comments. If something is unused, remove it.

## Testing

**Context-dependent.** Not every task requires tests. Config, scripts, documentation, exploratory work — don't test these by default. Prototyping may defer tests entirely. Match testing effort to what's actually at risk, not to a coverage target.
