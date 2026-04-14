---
name: security-review
description: Focused security analysis of code changes. Identify injection vulnerabilities, auth/authz flaws, secrets exposure, input validation gaps, data leaks, and cryptography issues. Use when reviewing code with authentication, authorization, user input handling, API endpoints, or data processing.
disable-model-invocation: true
---

# Security Reviewer

Identify security risks in code changes with high precision. Report findings — do not make changes directly.

## Workflow

### Step 1: Determine Scope

Use the scope provided by the user. If none specified, default to unstaged changes:

```bash
git diff --name-only
```

For PR reviews:

```bash
gh pr diff <NUMBER> --name-only
```

### Step 2: Identify Attack Surface

Read each changed file. Identify:
- User input entry points (API endpoints, form handlers, CLI args)
- Data flows from untrusted sources
- Authentication and authorization boundaries
- External service integrations
- File system and database operations

### Step 3: Analyze

Trace untrusted data from input through processing to output. Check controls at each boundary. Evaluate against these focus areas:

**Injection Vulnerabilities**
- SQL injection via unsanitized queries
- Command injection through shell execution
- XSS through unescaped output
- Template injection in rendering engines
- LDAP/XML/path injection

**Authentication & Authorization**
- Missing or bypassable auth checks
- Broken access control (IDOR, privilege escalation)
- Session management flaws
- Insecure token handling
- Authentication logic errors

**Secrets & Credentials**
- Hardcoded credentials in code
- Secrets in logs or error messages
- Insecure secret storage
- API keys in client-side code
- Credentials in version control

**Input Validation**
- Missing or incomplete validation
- Type coercion vulnerabilities
- Length/size limit bypasses
- Format string vulnerabilities
- Deserialization risks

**Data Exposure**
- Sensitive data in responses
- Excessive data in error messages
- Information leakage via timing
- Insecure data transmission
- PII handling violations

**Cryptography**
- Weak algorithms (MD5, SHA1 for security)
- Hardcoded keys/IVs
- Improper random number generation
- Missing encryption where expected

### Step 4: Classify Severity

| Severity | Criteria | Examples |
|----------|----------|----------|
| 🔴 Critical | Remote exploit, data breach, auth bypass | SQL injection, RCE, auth bypass |
| 🟠 High | Significant risk, requires some conditions | XSS, CSRF, privilege escalation |
| 🟡 Medium | Limited impact or difficult to exploit | Information disclosure, weak crypto |
| 🟢 Low | Minimal impact, defense in depth | Missing headers, verbose errors |

### Step 5: Reduce False Positives

Before reporting each finding, verify:
1. The vulnerable code path is reachable
2. User-controlled input actually reaches the sink
3. No existing controls mitigate the risk
4. Exploitation is practical, not just theoretical

Only report findings that are real vulnerabilities or significant risks.

### Step 6: Report

```markdown
## Security Review Summary

**Risk Level**: [Critical / High / Medium / Low / Clean]
**Files Analyzed**: X files, Y entry points

### Critical Findings
[List or "None"]

### High Findings
[List or "None"]

### Medium/Low Findings
[List or "None"]

### Recommendations
- [Priority fixes]
- [Hardening suggestions]
```

For each finding:

```
[SEVERITY] Vulnerability Type — file:line

Description: What the vulnerability is and how it could be exploited.

Evidence: Specific code that demonstrates the issue.

Remediation: Concrete fix with code example if helpful.
```

## Scope

**In scope**: Security vulnerabilities, authentication/authorization, input validation, secrets handling, data exposure, cryptography.

**Out of scope**: General code quality, performance, test coverage (except security tests), architectural decisions.
