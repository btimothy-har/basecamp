---
name: gh-issue
description: Create or edit a GitHub issue.
argument-hint: "[#number] <description>"
disable-model-invocation: true
---

# GitHub Issue

Create a new issue or edit an existing one.

## Input

$ARGUMENTS

## Detect Intent

- Starts with `#N` or a number → **edit** that issue
- Otherwise → **create** a new issue

## Process

### 1. Summarize Context

From the current conversation and `$ARGUMENTS`, build a self-contained prompt. The issue-worker agent has no conversation history — the prompt must carry everything.

Include:
- What was observed or requested
- Relevant file paths, modules, or areas already discussed
- Why it matters or needs follow-up
- For edits: the issue number and what should change

### 2. Dispatch

Launch the **issue-worker** agent in the background with the summarized prompt.

Do not wait for it to complete. Report that the issue is being created in the background.
