---
name: gh-issue
description: Capture context as a GitHub issue.
argument-hint: "<what to capture>"
disable-model-invocation: true
---

# Capture as GitHub Issue

Turn a discovery, decision, or observation into a trackable GitHub issue.

## Input

$ARGUMENTS

## Process

### 1. Build Prompt

The issue-worker agent has no conversation history — the prompt must be self-contained.

From the input above and any relevant conversation context, build a prompt that includes:
- What was observed, discovered, or decided
- Relevant file paths, modules, or areas
- Why it matters or needs follow-up

Keep it focused — extract only what's relevant to the issue, not the full conversation.

### 2. Dispatch

Launch the **issue-worker** agent in the background with the prompt.

Do not wait for it to complete. Report that the issue is being captured in the background.
