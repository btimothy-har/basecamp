/** Fork inheritance: transcript-header parsing and parent-state field carry-over. */

import * as fs from "node:fs";
import type { ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import type { BasecampSessionState } from "./model.ts";
import { isRecord, loadSessionState } from "./persistence.ts";

function readFirstJsonlLine(filePath: string): string | null {
	// Transcripts can be large; read only until the header newline instead of loading the whole file.
	let fd: number | null = null;
	try {
		fd = fs.openSync(filePath, "r");
		const buffer = Buffer.alloc(4096);
		const chunks: string[] = [];
		let totalBytes = 0;
		const maxHeaderBytes = 64 * 1024;

		while (totalBytes < maxHeaderBytes) {
			const bytesRead = fs.readSync(fd, buffer, 0, Math.min(buffer.length, maxHeaderBytes - totalBytes), null);
			if (bytesRead === 0) break;

			const chunk = buffer.subarray(0, bytesRead).toString("utf8");
			const newlineIndex = chunk.indexOf("\n");
			if (newlineIndex >= 0) {
				chunks.push(chunk.slice(0, newlineIndex));
				return chunks.join("");
			}

			chunks.push(chunk);
			totalBytes += bytesRead;
		}

		return chunks.length > 0 ? chunks.join("") : null;
	} catch {
		return null;
	} finally {
		if (fd !== null) fs.closeSync(fd);
	}
}

export function readSessionIdFromTranscriptHeader(sessionFile: string): string | null {
	const line = readFirstJsonlLine(sessionFile);
	if (!line) return null;

	try {
		const parsed: unknown = JSON.parse(line);
		if (!isRecord(parsed)) return null;
		if (parsed.type !== "session") return null;
		return typeof parsed.id === "string" ? parsed.id : null;
	} catch {
		return null;
	}
}

function getParentSessionFileFromHeader(ctx: ExtensionContext): string | null {
	try {
		const parentSession = ctx.sessionManager.getHeader()?.parentSession;
		return typeof parentSession === "string" && parentSession.length > 0 ? parentSession : null;
	} catch {
		return null;
	}
}

export function resolveParentSessionFile(event: SessionStartEvent, ctx: ExtensionContext): string | null {
	if (typeof event.previousSessionFile === "string" && event.previousSessionFile.length > 0) {
		return event.previousSessionFile;
	}
	return getParentSessionFileFromHeader(ctx);
}

export function loadForkInheritedFields(
	parentSessionFile: string,
	stateDir?: string,
): Pick<BasecampSessionState, "activeWorktree" | "agentMode" | "title"> | null {
	const parentSessionId = readSessionIdFromTranscriptHeader(parentSessionFile);
	if (!parentSessionId) return null;

	const parentState = loadSessionState({ sessionId: parentSessionId, sessionFile: parentSessionFile }, stateDir);
	return {
		activeWorktree: parentState.activeWorktree
			? { ...parentState.activeWorktree, worktree: { ...parentState.activeWorktree.worktree } }
			: null,
		agentMode: parentState.agentMode,
		title: parentState.title,
	};
}
