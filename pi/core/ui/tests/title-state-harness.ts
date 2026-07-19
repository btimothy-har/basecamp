import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";

export async function createTempDir(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-title-session-"));
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

export function messageEntry(message: unknown): SessionEntry {
	return { type: "message", message } as unknown as SessionEntry;
}

interface TestContextOptions {
	sessionId: string;
	branch?: SessionEntry[];
	onTitle?: (title: string) => void;
	onWidget?: (widget: unknown) => void;
	onNotify?: (message: string, level?: string) => void;
}

export function createContext({
	sessionId,
	branch = [],
	onTitle = () => {},
	onWidget = () => {},
	onNotify = () => {},
}: TestContextOptions): ExtensionContext {
	return {
		hasUI: true,
		ui: {
			setTitle: onTitle,
			setWidget: (_id: string, widget: unknown) => onWidget(widget),
			notify: onNotify,
		},
		sessionManager: {
			getSessionId: () => sessionId,
			getSessionFile: () => null,
			getBranch: () => branch,
		},
	} as unknown as ExtensionContext;
}

export function createPi() {
	const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => Promise<void> | void>();
	const commands = new Map<string, { handler: (args: string[], ctx: ExtensionContext) => Promise<void> }>();
	const sessionNames: string[] = [];
	const pi = {
		on: (event: string, handler: (event: unknown, ctx: ExtensionContext) => Promise<void> | void) => {
			handlers.set(event, handler);
		},
		registerCommand: (name: string, command: { handler: (args: string[], ctx: ExtensionContext) => Promise<void> }) => {
			commands.set(name, command);
		},
		setSessionName: (name: string) => sessionNames.push(name),
	} as unknown as ExtensionAPI;

	return { pi, handlers, commands, sessionNames };
}

export async function flushBackgroundTitle(): Promise<void> {
	await new Promise<void>((resolve) => setImmediate(resolve));
}
