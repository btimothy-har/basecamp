import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { buildSessionStatePath } from "../index.ts";

export async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-session-state-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

export async function writeStateFile(stateDir: string, sessionId: string, content: unknown): Promise<void> {
	const filePath = buildSessionStatePath(sessionId, stateDir);
	await fs.mkdir(path.dirname(filePath), { recursive: true });
	const text = typeof content === "string" ? content : JSON.stringify(content);
	await fs.writeFile(filePath, text ?? "null", "utf8");
}

export async function writeTranscriptHeader(filePath: string, sessionId: string): Promise<void> {
	await fs.mkdir(path.dirname(filePath), { recursive: true });
	await fs.writeFile(
		filePath,
		`${JSON.stringify({ type: "session", version: 3, id: sessionId, timestamp: "2026-01-01T00:00:00.000Z", cwd: "/tmp" })}\n${JSON.stringify({ type: "message", id: "m1", parentId: null })}\n`,
		"utf8",
	);
}

export function createContext(sessionId: string, sessionFile?: string, parentSession?: string): ExtensionContext {
	return {
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => sessionFile,
			getHeader: () => ({
				type: "session",
				version: 3,
				id: sessionId,
				timestamp: "2026-01-01T00:00:00.000Z",
				cwd: "/tmp",
				parentSession,
			}),
		},
	} as unknown as ExtensionContext;
}
