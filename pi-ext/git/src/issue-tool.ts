/**
 * publish_issue tool — publishes a file-backed GitHub issue draft after review.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { exec } from "../../platform/exec";
import { requireSessionState } from "../../platform/session";
import { activeIssueDraft, clearActiveIssueDraft } from "./guards";
import { showIssueReview } from "./issue-review";
import { getIssueDraftDir } from "./utils";

const MAX_DRAFT_BYTES = 64 * 1024;
const PRIVATE_FILE_MODE = 0o600;

interface RepoInfo {
	nameWithOwner: string;
	visibility: string;
	url: string;
}

interface ParsedIssueDraft {
	title: string;
	body: string;
}

interface SecretPattern {
	name: string;
	regex: RegExp;
}

const SECRET_PATTERNS: SecretPattern[] = [
	{
		name: "GitHub token",
		regex: /\b(?:gh[pousr]_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{22,}_[A-Za-z0-9_]{59,})\b/,
	},
	{
		name: "AWS access key ID",
		regex: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/,
	},
	{
		name: "private key block",
		regex: /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----/,
	},
	{
		name: "generic API key or token assignment",
		regex:
			/\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|secret[_-]?key|token)\b\s*[:=]\s*["']?[A-Za-z0-9_./+=-]{20,}/i,
	},
];

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function isErrorWithCode(error: unknown, code: string): boolean {
	return typeof error === "object" && error !== null && "code" in error && error.code === code;
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function realpathOrThrow(targetPath: string, label: string): string {
	try {
		return fs.realpathSync(targetPath);
	} catch (error) {
		throw new Error(`${label} is unavailable: ${errorMessage(error)}`);
	}
}

function lstatOrThrow(targetPath: string, label: string): fs.Stats {
	try {
		return fs.lstatSync(targetPath);
	} catch (error) {
		if (isErrorWithCode(error, "ENOENT")) throw new Error(`${label} does not exist: ${targetPath}`);
		throw new Error(`Unable to inspect ${label}: ${errorMessage(error)}`);
	}
}

function normalizeRemoteRepoPath(rawPath: string): string {
	return rawPath
		.trim()
		.replace(/^\/+/, "")
		.replace(/\/+$/, "")
		.replace(/\.git$/i, "");
}

function buildGhRepoTarget(hostValue: string, rawRepoPath: string, remoteUrl: string): string {
	const host = hostValue.trim().toLowerCase();
	if (!host) throw new Error(`Unable to derive GitHub repository target from remote URL: ${remoteUrl}`);

	const parts = normalizeRemoteRepoPath(rawRepoPath).split("/").filter(Boolean);
	if (parts.length !== 2) {
		throw new Error(`Remote URL must identify an OWNER/REPO GitHub repository: ${remoteUrl}`);
	}

	const owner = parts[0];
	const repo = parts[1];
	if (!owner || !repo) throw new Error(`Remote URL must identify an OWNER/REPO GitHub repository: ${remoteUrl}`);

	const ownerRepo = `${owner}/${repo}`;
	return host === "github.com" ? ownerRepo : `${host}/${ownerRepo}`;
}

function repoTargetFromRemoteUrl(remoteUrl: string): string {
	const trimmed = remoteUrl.trim();
	if (!trimmed) throw new Error("Cannot publish issue: git remote URL is not configured for this session.");

	const scpLike = trimmed.match(/^(?:[^@/:]+@)?([^:/]+):(.+)$/);
	if (!trimmed.includes("://") && scpLike) {
		const host = scpLike[1];
		const repoPath = scpLike[2];
		if (host && repoPath) return buildGhRepoTarget(host, repoPath, trimmed);
	}

	try {
		const parsed = new URL(trimmed);
		return buildGhRepoTarget(parsed.hostname, parsed.pathname, trimmed);
	} catch (error) {
		throw new Error(`Unable to parse git remote URL for GitHub publishing: ${errorMessage(error)}`);
	}
}

function getSessionRepoTarget(): string {
	const state = requireSessionState();
	if (!state.isRepo) throw new Error("Cannot publish issue: Basecamp session is not in a git repository.");
	if (!state.remoteUrl?.trim())
		throw new Error("Cannot publish issue: git remote URL is not configured for this session.");
	return repoTargetFromRemoteUrl(state.remoteUrl);
}

function validateDraftPath(draftPath: string, activeDraftPath: string, cwd: string): string {
	const issueDirReal = realpathOrThrow(getIssueDraftDir(cwd), "Issue draft directory");
	const requestedAbs = path.resolve(cwd, draftPath);
	const activeAbs = path.resolve(cwd, activeDraftPath);
	const requestedParentReal = realpathOrThrow(path.dirname(requestedAbs), "Issue draft parent directory");

	if (!isPathWithin(requestedParentReal, issueDirReal)) {
		throw new Error("Issue draft path must stay under the Basecamp issue draft directory.");
	}

	if (requestedAbs !== activeAbs) {
		throw new Error(`Draft path does not match the active /create-issue draft. Use: ${activeDraftPath}`);
	}

	const stat = lstatOrThrow(requestedAbs, "Issue draft file");
	if (stat.isSymbolicLink()) throw new Error("Issue draft path must not be a symlink.");
	if (!stat.isFile()) throw new Error("Issue draft path must be a regular markdown file.");
	if (stat.size > MAX_DRAFT_BYTES) {
		throw new Error(`Issue draft is too large (${stat.size} bytes). Limit is ${MAX_DRAFT_BYTES} bytes.`);
	}

	return requestedAbs;
}

function parseIssueDraft(markdown: string): ParsedIssueDraft {
	const lines = markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
	const titleIndex = lines.findIndex((line) => line.trim().length > 0);
	if (titleIndex === -1) throw new Error("Issue draft is empty. Add a '# Title' heading and body.");

	const titleLine = lines[titleIndex]!;

	const titleMatch = titleLine.trimEnd().match(/^#(?!#)\s+(.+?)\s*$/);
	if (!titleMatch) {
		throw new Error("First non-empty line must be a single H1 heading like '# Issue title'.");
	}

	const title = titleMatch[1]?.trim() ?? "";
	if (!title) throw new Error("Issue title must not be empty.");
	if (title.length > 200) throw new Error("Issue title must be 200 characters or fewer.");

	const bodyLines = lines.slice(titleIndex + 1);
	while (bodyLines.length > 0 && bodyLines[0]?.trim().length === 0) bodyLines.shift();
	const body = bodyLines.join("\n").trimEnd();
	if (!body.trim()) throw new Error("Issue body must not be empty.");

	return { title, body };
}

function entropy(value: string): number {
	const counts = new Map<string, number>();
	for (const char of value) counts.set(char, (counts.get(char) ?? 0) + 1);

	let total = 0;
	for (const count of counts.values()) {
		const probability = count / value.length;
		total -= probability * Math.log2(probability);
	}
	return total;
}

function hasAtLeastThreeCharacterClasses(value: string): boolean {
	let classes = 0;
	if (/[a-z]/.test(value)) classes += 1;
	if (/[A-Z]/.test(value)) classes += 1;
	if (/[0-9]/.test(value)) classes += 1;
	return classes >= 3;
}

function hasHighEntropyToken(text: string): boolean {
	for (const match of text.matchAll(/\b[A-Za-z0-9]{48,}\b/g)) {
		const token = match[0];
		if (hasAtLeastThreeCharacterClasses(token) && entropy(token) >= 4) return true;
	}
	return false;
}

function assertNoSecrets(text: string): void {
	for (const pattern of SECRET_PATTERNS) {
		if (pattern.regex.test(text)) {
			throw new Error(`Issue draft contains a suspected secret (${pattern.name}). Remove it before publishing.`);
		}
	}

	if (hasHighEntropyToken(text)) {
		throw new Error(
			"Issue draft contains a suspected secret (high-entropy token-like string). Remove it before publishing.",
		);
	}
}

function assertNoTerminalControlSequences(text: string, label: string): void {
	for (let index = 0; index < text.length; index += 1) {
		const code = text.charCodeAt(index);
		const isAllowedWhitespace = code === 0x09 || code === 0x0a || code === 0x0d;
		const isControl = code <= 0x1f || (code >= 0x7f && code <= 0x9f);

		if (isControl && !isAllowedWhitespace) {
			throw new Error(
				`${label} contains terminal/control characters. Remove ANSI/OSC escape sequences and control characters before review or publishing.`,
			);
		}
	}
}

function stringField(value: unknown, key: string): string | null {
	if (typeof value !== "object" || value === null) return null;
	const field = (value as Record<string, unknown>)[key];
	return typeof field === "string" && field.trim() ? field : null;
}

function parseRepoInfo(output: string): RepoInfo {
	let parsed: unknown;
	try {
		parsed = JSON.parse(output);
	} catch (error) {
		throw new Error(`Unable to parse repository information from gh: ${errorMessage(error)}`);
	}

	const nameWithOwner = stringField(parsed, "nameWithOwner");
	const visibility = stringField(parsed, "visibility");
	const url = stringField(parsed, "url");
	if (!nameWithOwner || !visibility || !url) {
		throw new Error("gh repo view did not return nameWithOwner, visibility, and url.");
	}

	return { nameWithOwner, visibility, url };
}

async function resolveRepo(pi: ExtensionAPI, repoTarget: string): Promise<RepoInfo> {
	const result = await exec(pi, "gh", ["repo", "view", repoTarget, "--json", "nameWithOwner,visibility,url"]);
	if (result.code !== 0) {
		throw new Error(
			`Unable to resolve GitHub repository ${repoTarget} with gh repo view: ${result.stderr.trim() || result.stdout.trim()}`,
		);
	}
	return parseRepoInfo(result.stdout.trim());
}

function createBodyFile(cwd: string, body: string): string {
	const issueDir = getIssueDraftDir(cwd);

	for (let attempt = 0; attempt < 10; attempt += 1) {
		const bodyPath = path.join(issueDir, `body-${Date.now()}-${crypto.randomBytes(8).toString("hex")}.md`);
		let fd: number | null = null;
		try {
			fd = fs.openSync(bodyPath, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY, PRIVATE_FILE_MODE);
			fs.writeFileSync(fd, body, "utf8");
			fs.chmodSync(bodyPath, PRIVATE_FILE_MODE);
			return bodyPath;
		} catch (error) {
			if (isErrorWithCode(error, "EEXIST")) continue;
			try {
				fs.rmSync(bodyPath, { force: true });
			} catch {}
			throw error;
		} finally {
			if (fd !== null) fs.closeSync(fd);
		}
	}

	throw new Error("Unable to allocate a unique issue body file.");
}

export function registerIssueTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "publish_issue",
		label: "Publish Issue",
		description:
			"Submit the markdown issue draft created by /create-issue for user review. User can approve to publish, " +
			"provide feedback for revision, or cancel. Only available after /create-issue has been invoked.",
		promptSnippet: "Show issue draft for review — user can publish or give feedback for revision",
		parameters: Type.Object(
			{
				draftPath: Type.String({ description: "path to the markdown issue draft created by /create-issue" }),
			},
			{ additionalProperties: false },
		),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const draft = activeIssueDraft;
			if (!draft) {
				throw new Error("No active issue draft. Run /create-issue first.");
			}

			if (!ctx.hasUI) {
				throw new Error("publish_issue requires an interactive UI. Run /create-issue in an interactive session.");
			}

			if (pi.getFlag("read-only") === true) {
				throw new Error("publish_issue is disabled in read-only mode.");
			}

			const draftPath = validateDraftPath(params.draftPath, draft.draftPath, ctx.cwd);
			const markdown = fs.readFileSync(draftPath, "utf8");
			assertNoTerminalControlSequences(markdown, "Issue draft");
			assertNoTerminalControlSequences(draft.topic, "Issue topic");
			assertNoSecrets(markdown);
			const { title, body } = parseIssueDraft(markdown);

			const repoTarget = getSessionRepoTarget();
			const repoInfo = await resolveRepo(pi, repoTarget);
			const review = await showIssueReview(
				{
					repoTarget,
					repo: repoInfo.nameWithOwner,
					visibility: repoInfo.visibility,
					draftPath,
					title,
					body,
					topic: draft.topic,
				},
				ctx,
			);

			if (review.action === "cancel") {
				return {
					content: [
						{
							type: "text",
							text: `User cancelled issue publishing. No GitHub issue was created. The draft remains active at ${draftPath}.`,
						},
					],
					details: null,
				};
			}

			if (review.action === "feedback") {
				return {
					content: [
						{
							type: "text",
							text: `User feedback on issue draft:\n\n${review.text}\n\nEdit the same draft file at ${draftPath}, then call publish_issue again with the same draftPath.`,
						},
					],
					details: null,
				};
			}

			const bodyFile = createBodyFile(ctx.cwd, body);
			let ghResult: Awaited<ReturnType<ExtensionAPI["exec"]>>;
			try {
				ghResult = await exec(pi, "gh", [
					"issue",
					"create",
					"--repo",
					repoTarget,
					"--title",
					title,
					"--body-file",
					bodyFile,
				]);
			} finally {
				fs.rmSync(bodyFile, { force: true });
			}

			if (ghResult.code !== 0) {
				throw new Error(
					`Failed to create GitHub issue: ${ghResult.stderr.trim() || ghResult.stdout.trim()}\nDraft: ${draftPath}`,
				);
			}

			const issueUrl = ghResult.stdout.trim();
			clearActiveIssueDraft();

			return {
				content: [
					{
						type: "text",
						text: `Issue published.\nURL: ${issueUrl}\nDraft: ${draftPath}`,
					},
				],
				details: null,
			};
		},
	});
}
