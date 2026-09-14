import { afterEach, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import type {
	AgentEndEvent,
	ExtensionAPI,
	SessionStartEvent,
	ToolResultEvent,
} from "@oh-my-pi/pi-coding-agent";
import registerFileLengthReminder from "../file-length.ts";

interface TestContext {
	cwd: string;
}

type EventHandler<Event> = (event: Event, ctx: TestContext) => unknown;

interface EventHandlers {
	session_start: EventHandler<SessionStartEvent>;
	agent_end: EventHandler<AgentEndEvent>;
	tool_result: EventHandler<ToolResultEvent>;
}

interface ReminderMessage {
	customType: string;
	content: string;
	display: boolean;
}

interface ReminderOptions {
	triggerTurn?: boolean;
	deliverAs?: "steer" | "followUp" | "nextTurn" | "aside";
}

interface SentReminder {
	message: ReminderMessage;
	options: ReminderOptions | undefined;
}

const temporaryDirectories: string[] = [];

afterEach(() => {
	for (const directory of temporaryDirectories.splice(0)) {
		rmSync(directory, { recursive: true, force: true });
	}
});

function temporaryDirectory(): string {
	const directory = mkdtempSync(path.join(tmpdir(), "basecamp-omp-file-length-"));
	temporaryDirectories.push(directory);
	return directory;
}

function writeLines(filePath: string, count: number): void {
	mkdirSync(path.dirname(filePath), { recursive: true });
	writeFileSync(filePath, "line\n".repeat(count), "utf8");
}

function toolResultEvent(
	toolName: string,
	input: Record<string, unknown>,
	isError = false,
): ToolResultEvent {
	return {
		type: "tool_result",
		toolCallId: "call-1",
		toolName,
		input,
		content: [],
		details: undefined,
		isError,
	};
}

function createHarness(initialCwd = process.cwd()) {
	const handlers: Partial<EventHandlers> = {};
	const sent: SentReminder[] = [];
	let cwd = initialCwd;
	let sendError: Error | undefined;

	const api = {
		on<EventName extends keyof EventHandlers>(
			eventName: EventName,
			handler: EventHandlers[EventName],
		): void {
			handlers[eventName] = handler;
		},
		sendMessage(message: ReminderMessage, options?: ReminderOptions): void {
			if (sendError) throw sendError;
			sent.push({ message, options });
		},
	};

	registerFileLengthReminder(api as unknown as ExtensionAPI);

	function handler<EventName extends keyof EventHandlers>(
		eventName: EventName,
	): EventHandlers[EventName] {
		const registered = handlers[eventName];
		if (!registered) throw new Error(`${eventName} handler was not registered`);
		return registered;
	}

	return {
		sent,
		setCwd(nextCwd: string): void {
			cwd = nextCwd;
		},
		setSendError(error: Error | undefined): void {
			sendError = error;
		},
		async emit(toolName: string, input: Record<string, unknown>, isError = false): Promise<void> {
			await handler("tool_result")(toolResultEvent(toolName, input, isError), { cwd });
		},
		async sessionStart(): Promise<void> {
			await handler("session_start")({ type: "session_start" }, { cwd });
		},
		async agentEnd(event: AgentEndEvent): Promise<void> {
			await handler("agent_end")(event, { cwd });
		},
	};
}

const EXACT_CAPS: ReadonlyArray<readonly [suffix: string, cap: number]> = [
	["html", 350],
	["htm", 350],
	["ts", 350],
	["tsx", 350],
	["bash", 400],
	["sh", 400],
	["zsh", 400],
	["sql", 800],
	["py", 500],
];

describe("OMP file-length reminder", () => {
	test("applies exact suffix caps at their boundaries for successful edit and write results", async () => {
		const directory = temporaryDirectory();
		const harness = createHarness();

		for (const [index, [suffix, cap]] of EXACT_CAPS.entries()) {
			const target = path.join(directory, `source-${index}.${suffix}`);
			const toolName = index % 2 === 0 ? "edit" : "write";
			writeLines(target, cap);
			await harness.emit(toolName, { path: target });
			expect(harness.sent).toHaveLength(index);

			writeLines(target, cap + 1);
			await harness.emit(toolName, { path: target });
			expect(harness.sent).toHaveLength(index + 1);
			expect(harness.sent.at(-1)?.message.content).toContain(
				`is now ${cap + 1} lines, over the ${cap}-line cap for .${suffix}`,
			);
		}
	});

	test("matches recognized suffixes case-insensitively", async () => {
		const target = path.join(temporaryDirectory(), "MODULE.PY");
		writeLines(target, 501);
		const harness = createHarness();

		await harness.emit("write", { path: target });

		expect(harness.sent).toHaveLength(1);
		expect(harness.sent[0]?.message.content).toContain("500-line cap for .py source files");
	});

	test("filters unrelated tools, errors, missing paths, and unrecognized suffixes", async () => {
		const directory = temporaryDirectory();
		const source = path.join(directory, "large.ts");
		const unrecognized = path.join(directory, "large.md");
		writeLines(source, 351);
		writeLines(unrecognized, 1_000);
		const harness = createHarness();

		await harness.emit("read", { path: source });
		await harness.emit("edit", { path: source }, true);
		await harness.emit("edit", {});
		await harness.emit("write", { path: "" });
		await harness.emit("write", { path: unrecognized });

		expect(harness.sent).toEqual([]);
	});

	test("resolves relative paths against the live event cwd", async () => {
		const firstDirectory = temporaryDirectory();
		const secondDirectory = temporaryDirectory();
		const relativePath = path.join("nested", "module.ts");
		const firstTarget = path.join(firstDirectory, relativePath);
		const secondTarget = path.join(secondDirectory, relativePath);
		writeLines(firstTarget, 351);
		writeLines(secondTarget, 351);
		const harness = createHarness(firstDirectory);

		await harness.emit("edit", { path: relativePath });
		harness.setCwd(secondDirectory);
		await harness.emit("edit", { path: relativePath });

		expect(harness.sent).toHaveLength(2);
		expect(harness.sent[0]?.message.content).toContain(JSON.stringify(firstTarget));
		expect(harness.sent[1]?.message.content).toContain(JSON.stringify(secondTarget));
	});

	test("sends the expected hidden advisory steer", async () => {
		const target = path.join(temporaryDirectory(), "module.py");
		writeLines(target, 501);
		const harness = createHarness();

		await harness.emit("write", { path: target });

		expect(harness.sent).toEqual([
			{
				message: {
					customType: "basecamp-file-length-reminder",
					content:
						"<system-reminder>\n" +
						`File-length reminder: ${JSON.stringify(target)} is now 501 lines, over the 500-line cap for .py source files. ` +
						"The edit succeeded; this is advisory. Split the file along genuine responsibility seams into focused modules. " +
						"Do not compress formatting or create continuation files merely to satisfy the cap, and follow any tighter project-specific limit.\n" +
						"</system-reminder>",
					display: false,
				},
				options: { deliverAs: "steer" },
			},
		]);
	});

	test("suppresses duplicates and re-arms after an under-cap observation", async () => {
		const target = path.join(temporaryDirectory(), "module.ts");
		const harness = createHarness();
		writeLines(target, 351);

		await harness.emit("edit", { path: target });
		await harness.emit("write", { path: target });
		expect(harness.sent).toHaveLength(1);

		writeLines(target, 350);
		await harness.emit("edit", { path: target });
		writeLines(target, 351);
		await harness.emit("write", { path: target });
		expect(harness.sent).toHaveLength(2);
	});

	test("swallows read and send failures and retries on later observations", async () => {
		const target = path.join(temporaryDirectory(), "module.ts");
		const harness = createHarness();

		await expect(harness.emit("edit", { path: target })).resolves.toBeUndefined();
		writeLines(target, 351);
		harness.setSendError(new Error("delivery failed"));
		await expect(harness.emit("edit", { path: target })).resolves.toBeUndefined();
		expect(harness.sent).toEqual([]);

		harness.setSendError(undefined);
		await harness.emit("edit", { path: target });
		expect(harness.sent).toHaveLength(1);
	});

	test("re-arms on session start and only terminal agent end events", async () => {
		const target = path.join(temporaryDirectory(), "module.ts");
		writeLines(target, 351);
		const harness = createHarness();
		await harness.emit("edit", { path: target });

		await harness.agentEnd({ type: "agent_end", messages: [], willContinue: true });
		await harness.emit("edit", { path: target });
		expect(harness.sent).toHaveLength(1);

		await harness.agentEnd({ type: "agent_end", messages: [], willContinue: false });
		await harness.emit("edit", { path: target });
		expect(harness.sent).toHaveLength(2);

		await harness.agentEnd({ type: "agent_end", messages: [] });
		await harness.emit("edit", { path: target });
		expect(harness.sent).toHaveLength(3);

		await harness.sessionStart();
		await harness.emit("edit", { path: target });
		expect(harness.sent).toHaveLength(4);
	});
});
