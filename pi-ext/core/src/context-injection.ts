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
import { type ContextFile, loadContextFileFromDir } from "../../context";
import { getEffectiveCwd } from "./session";

// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------

/** Paths already injected this session — never send the same file twice. */
const injectedPaths = new Set<string>();

/** Directories whose CLAUDE.md is already in the system prompt (cwd → root). */
let systemPromptDirs: Set<string> | null = null;

/**
 * Build the set of directories that already have their context file in the
 * system prompt. Called lazily on first tool_result so session state is ready.
 */
function getSystemPromptDirs(): Set<string> {
	if (systemPromptDirs) return systemPromptDirs;

	systemPromptDirs = new Set<string>();
	let dir = getEffectiveCwd();
	while (true) {
		systemPromptDirs.add(dir);
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}

	return systemPromptDirs;
}

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

/**
 * Walk from `startDir` upward, stopping before any directory already
 * covered by the system prompt. Returns new context files in root-first
 * order (closest-to-cwd first, then deeper ancestors).
 */
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

// ---------------------------------------------------------------------------
// Message formatting
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

/** Extract file path from a tool_result event's input. */
function getFilePath(event: { toolName: string; input: Record<string, unknown> }): string | null {
	const p = event.input.path;
	return typeof p === "string" ? p : null;
}

export function registerContextInjection(pi: ExtensionAPI): void {
	pi.on("tool_result", async (event) => {
		// Only act on successful read/edit/write
		if (event.isError) return;
		if (!isReadToolResult(event) && !isEditToolResult(event) && !isWriteToolResult(event)) {
			return;
		}

		const filePath = getFilePath(event);
		if (!filePath) return;

		// Resolve to absolute path
		const resolved = path.isAbsolute(filePath) ? path.resolve(filePath) : path.resolve(getEffectiveCwd(), filePath);
		const fileDir = path.dirname(resolved);

		// Discover new context files between this file's dir and the system prompt boundary
		const newFiles = discoverNestedContextFiles(fileDir);
		if (newFiles.length === 0) return;

		// Mark as injected before sending
		for (const f of newFiles) {
			injectedPaths.add(f.path);
		}

		// Steer the message into the conversation
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
