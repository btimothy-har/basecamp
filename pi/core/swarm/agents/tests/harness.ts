import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach } from "node:test";
import { resetAgentRoleForTesting } from "../../../agent-role.ts";
import type { Frame } from "../../../hub/protocol/index.ts";
import type { WorkspaceState } from "../../../project/workspace/state.ts";
import type { DaemonConnection } from "../client.ts";

export interface RegisteredTool {
	name: string;
	description?: string;
	execute: (id: string, params: any, signal: AbortSignal, onUpdate: () => void, ctx: any) => Promise<any>;
}

export class MockConnection implements DaemonConnection {
	sent: Frame[] = [];
	handlers = new Map<Frame["type"], Set<(frame: any) => void>>();
	closeHandlers = new Set<(code: number, reason: string) => void>();

	send(frame: Frame): void {
		this.sent.push(frame);
	}

	on<T extends Frame["type"]>(type: T, handler: (frame: Extract<Frame, { type: T }>) => void): () => void {
		const set = this.handlers.get(type) ?? new Set();
		set.add(handler as any);
		this.handlers.set(type, set);
		return () => set.delete(handler as any);
	}

	onClose(handler: (code: number, reason: string) => void): () => void {
		this.closeHandlers.add(handler);
		return () => this.closeHandlers.delete(handler);
	}

	close(): void {
		this.emitClose(1000, "client closed");
	}

	emit(frame: Frame): void {
		const set = this.handlers.get(frame.type);
		if (!set) return;
		for (const handler of set) handler(frame as any);
	}

	emitClose(code: number, reason: string): void {
		for (const handler of this.closeHandlers) handler(code, reason);
	}
}

export class MockPi {
	tools: RegisteredTool[] = [];
	handlers = new Map<string, ((event: any, ctx: any) => unknown)[]>();

	registerTool(tool: RegisteredTool): void {
		this.tools.push(tool);
	}

	on(event: string, handler: (event: any, ctx: any) => unknown): void {
		this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
	}

	getSessionName(): string {
		return "session-name";
	}

	getAllTools(): unknown[] {
		return [];
	}

	sendUserMessage(): void {}

	setSessionName(_name: string): void {}

	async emit(type: string, event: unknown): Promise<void> {
		for (const handler of this.handlers.get(type) ?? []) {
			await handler(event, undefined);
		}
	}
}

export function createMockPi() {
	const pi = new MockPi();
	return { pi: pi as any, tools: pi.tools, handlers: pi.handlers };
}

export function toolByName(tools: RegisteredTool[], name: string): RegisteredTool {
	const tool = tools.find((candidate) => candidate.name === name);
	assert.ok(tool, `Missing tool ${name}`);
	return tool;
}

const invokedSkills = new Set<string>();
let currentWorkspaceState: WorkspaceState | null = null;

export function trackSkillInvocation(name: string): void {
	invokedSkills.add(name);
}

export function resetInvokedSkills(): void {
	invokedSkills.clear();
}

export function setCurrentWorkspaceState(value: WorkspaceState | null): void {
	currentWorkspaceState = value;
}

export const daemonToolDeps = {
	hasInvokedSkill: (name: string) => invokedSkills.has(name),
	getWorkspaceState: () => currentWorkspaceState,
	basecampExtensionRoot: process.cwd(),
	resolveModelAlias: (model: string) => model,
};

/**
 * Reproduces the shared per-test setup of the original daemon-tools suite:
 * tmp HOME dir, invoked-skill reset, workspace-state reset, agent-role reset.
 * Call inside a describe block so the hooks scope to that suite.
 */
export function installDaemonToolTestHooks(): void {
	let priorHome: string | undefined;
	let tmpHome: string;

	beforeEach(() => {
		priorHome = process.env.HOME;
		tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "bc-test-home-"));
		process.env.HOME = tmpHome;
		resetInvokedSkills();
	});

	afterEach(() => {
		if (priorHome === undefined) delete process.env.HOME;
		else process.env.HOME = priorHome;
		fs.rmSync(tmpHome, { recursive: true, force: true });
		currentWorkspaceState = null;
		resetInvokedSkills();
		resetAgentRoleForTesting();
	});
}
