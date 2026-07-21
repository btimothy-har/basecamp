import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getPaneState, setCompanionActive } from "../panes/state.ts";

type Handler = (event: unknown, ctx: MockContext) => unknown;

type ExecResult = { code: number; stdout: string; stderr: string };

type ExecHandler = (command: string, args: string[]) => Promise<ExecResult> | ExecResult;

type StatusSetCall = { key: string; value: string | undefined };

export interface MockContext {
	hasUI: boolean;
	sessionManager: { getSessionId(): string };
	ui: {
		notifications: Array<{ message: string; level: string }>;
		statusCalls: StatusSetCall[];
		theme: { fg(color: string, text: string): string };
		notify(message: string, level: string): void;
		setStatus(key: string, value: string | undefined): void;
	};
}

export function resetPaneState(): void {
	const state = getPaneState();
	state.provider = null;
	state.paneId = null;
	setCompanionActive(false);
}

export function createContext(overrides: Partial<MockContext> = {}): MockContext {
	const notifications: Array<{ message: string; level: string }> = [];
	const statusCalls: StatusSetCall[] = [];
	return {
		hasUI: true,
		sessionManager: { getSessionId: () => "session-1" },
		ui: {
			notifications,
			statusCalls,
			theme: { fg: (color: string, text: string) => `${color}:${text}` },
			notify(message: string, level: string) {
				notifications.push({ message, level });
			},
			setStatus(key: string, value: string | undefined) {
				statusCalls.push({ key, value });
			},
		},
		...overrides,
	};
}

export function createMockPi(execHandler: ExecHandler = () => ({ code: 0, stdout: "%9\n", stderr: "" })) {
	const handlers = new Map<string, Handler[]>();
	const execCalls: Array<{ command: string; args: string[] }> = [];
	const pi = {
		on(eventName: string, handler: Handler) {
			handlers.set(eventName, [...(handlers.get(eventName) ?? []), handler]);
		},
		async exec(command: string, args: string[]) {
			execCalls.push({ command, args });
			return execHandler(command, args);
		},
	};
	return {
		pi: pi as unknown as ExtensionAPI,
		execCalls,
		registeredEvents: () => [...handlers.keys()],
		handlerCount: (eventName: string) => handlers.get(eventName)?.length ?? 0,
		async emit(eventName: string, event: unknown = {}, ctx: MockContext = createContext()) {
			for (const handler of handlers.get(eventName) ?? []) {
				await handler(event, ctx);
			}
			return ctx;
		},
	};
}

export function withTmuxEnv(): void {
	process.env.TMUX = "/tmp/tmux.sock,123,0";
	process.env.TMUX_PANE = "%1";
	delete process.env.HERDR_ENV;
	delete process.env.HERDR_PANE_ID;
	delete process.env.HERDR_SOCKET_PATH;
	process.env.BASECAMP_AGENT_DEPTH = "0";
}

export function withHerdrEnv(): void {
	process.env.HERDR_ENV = "1";
	process.env.HERDR_PANE_ID = "w8:p1";
	process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
	process.env.BASECAMP_AGENT_DEPTH = "0";
}
