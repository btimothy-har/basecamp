/**
 * Mid-session context injection for nested CLAUDE.md / AGENTS.md files.
 *
 * At session start, only CLAUDE.md files in the cwd-to-root ancestor chain
 * are included in the system prompt. Subdirectory context files (e.g.
 * packages/api/CLAUDE.md) are invisible until the agent works in that area.
 *
 * This module hooks tool_result for read/edit/write. When a tool touches
 * a file, we walk from that file's directory up to (but not including)
 * directories already covered by the system prompt. Any newly discovered
 * CLAUDE.md / AGENTS.md is injected once as a steered message.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isEditToolResult, isReadToolResult, isWriteToolResult } from "@mariozechner/pi-coding-agent";
import { type ContextFile, loadContextFileFromDir } from "../../platform/context.ts";
import { getWorkspaceEffectiveCwd } from "../../platform/workspace.ts";

const injectedPaths = new Set<string>();
let systemPromptDirs: Set<string> | null = null;

function getSystemPromptDirs(): Set<string> {
	if (systemPromptDirs) return systemPromptDirs;

	systemPromptDirs = new Set<string>();
	let dir = getWorkspaceEffectiveCwd();
	while (true) {
		systemPromptDirs.add(dir);
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}

	return systemPromptDirs;
}

function discoverNestedContextFiles(startDir: string): ContextFile[] {
	const covered = getSystemPromptDirs();
	const files: ContextFile[] = [];

	let dir = startDir;
	while (true) {
		// Stop once we hit a directory already in the system prompt chain
		if (covered.has(dir)) break;

		const file = loadContextFileFromDir(dir);
		if (file && !injectedPaths.has(file.path)) {
			files.unshift(file); // root-first order
		}

		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}

	return files;
}

function formatInjectionMessage(files: ContextFile[]): string {
	const parts: string[] = [];

	for (const file of files) {
		const dir = path.dirname(file.path);
		parts.push(`## ${file.path}\n\nApplies to files under \`${dir}/\`\n\n${file.content}`);
	}

	return (
		"<system-reminder>\n" +
		"The following project instructions apply to the directory you are now working in. " +
		"Treat these as additional project context alongside the instructions in the system prompt.\n\n" +
		parts.join("\n\n") +
		"\n</system-reminder>"
	);
}

function getFilePath(event: { toolName: string; input: Record<string, unknown> }): string | null {
	const p = event.input.path;
	return typeof p === "string" ? p : null;
}

function resetContextInjectionState(): void {
	injectedPaths.clear();
	systemPromptDirs = null;
}

export function registerContextInjection(pi: ExtensionAPI): void {
	pi.on("session_start", resetContextInjectionState);
	pi.on("session_compact", resetContextInjectionState);

	pi.on("tool_result", async (event) => {
		// Only act on successful read/edit/write
		if (event.isError) return;
		if (!isReadToolResult(event) && !isEditToolResult(event) && !isWriteToolResult(event)) {
			return;
		}

		const filePath = getFilePath(event);
		if (!filePath) return;

		const resolved = path.isAbsolute(filePath)
			? path.resolve(filePath)
			: path.resolve(getWorkspaceEffectiveCwd(), filePath);
		const fileDir = path.dirname(resolved);

		const newFiles = discoverNestedContextFiles(fileDir);
		if (newFiles.length === 0) return;

		for (const f of newFiles) {
			injectedPaths.add(f.path);
		}

		pi.sendMessage(
			{
				customType: "context-injection",
				content: formatInjectionMessage(newFiles),
				display: false,
			},
			{ deliverAs: "steer" },
		);
	});
}
