import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI, ToolResultEvent } from "@earendil-works/pi-coding-agent";
import { registerFileLengthReminder } from "../file-length.ts";

interface SentReminder {
	message: { customType: string; content: string; display: boolean };
	options: { deliverAs: string; triggerTurn?: boolean };
}

interface HarnessOptions {
	cwd?: string;
	readText?: (filePath: string) => string;
	sendError?: Error;
}

type EventHandler = () => Promise<void> | void;
type ToolResultHandler = (event: ToolResultEvent) => Promise<void> | void;

function createHarness(options: HarnessOptions = {}) {
	let sessionStart: EventHandler = () => {
		throw new Error("session_start handler was not registered");
	};
	let settled: EventHandler = () => {
		throw new Error("agent_settled handler was not registered");
	};
	let toolResult: ToolResultHandler = () => {
		throw new Error("tool_result handler was not registered");
	};
	const sent: SentReminder[] = [];
	const pi = {
		on(name: string, handler: unknown) {
			if (name === "session_start") sessionStart = handler as EventHandler;
			if (name === "agent_settled") settled = handler as EventHandler;
			if (name === "tool_result") toolResult = handler as ToolResultHandler;
		},
		sendMessage(message: SentReminder["message"], sendOptions: SentReminder["options"]) {
			if (options.sendError) throw options.sendError;
			sent.push({ message, options: sendOptions });
		},
	} as unknown as ExtensionAPI;

	registerFileLengthReminder(pi, {
		getCwd: () => options.cwd ?? process.cwd(),
		readText: options.readText,
	});

	const emit = (toolName: string, input: Record<string, unknown>, isError = false): Promise<void> =>
		Promise.resolve(
			toolResult({
				type: "tool_result",
				toolCallId: "call-1",
				toolName,
				input,
				content: [],
				details: undefined,
				isError,
			} as ToolResultEvent),
		);

	return {
		emit,
		sessionStart: () => Promise.resolve(sessionStart()),
		settle: () => Promise.resolve(settled()),
		sent,
	};
}

function tempDir(t: TestContext): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-file-length-"));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	return dir;
}

function writeLines(filePath: string, count: number, trailingNewline = true): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const content = Array.from({ length: count }, (_, index) => `line ${index + 1}`).join("\n");
	fs.writeFileSync(filePath, trailingNewline && content ? `${content}\n` : content, "utf8");
}

const CAPPED_SUFFIXES: ReadonlyArray<readonly [string, number]> = [
	[".ts", 350],
	[".tsx", 350],
	[".html", 350],
	[".htm", 350],
	[".sh", 400],
	[".bash", 400],
	[".zsh", 400],
	[".sql", 800],
	[".css", 500],
	[".py", 500],
	[".pyi", 500],
	[".js", 500],
	[".jsx", 500],
	[".mjs", 500],
	[".cjs", 500],
	[".go", 500],
	[".rs", 500],
	[".java", 500],
	[".kt", 500],
	[".kts", 500],
	[".scala", 500],
	[".swift", 500],
	[".rb", 500],
	[".php", 500],
	[".lua", 500],
	[".jl", 500],
	[".c", 500],
	[".h", 500],
	[".cpp", 500],
	[".cc", 500],
	[".cxx", 500],
	[".hpp", 500],
	[".hh", 500],
	[".cs", 500],
];

describe("file-length reminder", () => {
	it("applies the exact source allowlist and cap boundaries", async (t) => {
		const dir = tempDir(t);
		const harness = createHarness();

		for (const [index, [suffix, cap]] of CAPPED_SUFFIXES.entries()) {
			const target = path.join(dir, `source-${index}${suffix}`);
			writeLines(target, cap);
			await harness.emit("edit", { path: target, edits: [] });
			assert.equal(harness.sent.length, index);

			writeLines(target, cap + 1, false);
			await harness.emit("write", { path: target, content: "unused" });
			const reminder = harness.sent.at(-1)?.message.content ?? "";
			assert.match(reminder, new RegExp(`is now ${cap + 1} lines`));
			assert.match(reminder, new RegExp(`over the ${cap}-line cap`));
		}

		assert.equal(harness.sent.length, CAPPED_SUFFIXES.length);
	});

	it("matches suffixes case-insensitively and exempts unlisted files", async (t) => {
		const dir = tempDir(t);
		const harness = createHarness();
		const upperCase = path.join(dir, "component.TS");
		writeLines(upperCase, 351);

		await harness.emit("edit", { path: upperCase, edits: [] });
		assert.equal(harness.sent.length, 1);
		assert.match(harness.sent[0]?.message.content ?? "", /350-line cap/);

		for (const name of [
			"README.md",
			"fixture.json",
			"config.yaml",
			"settings.toml",
			"package.lock",
			"Dockerfile",
			"styles.scss",
		]) {
			const target = path.join(dir, name);
			writeLines(target, 1_000);
			await harness.emit("write", { path: target, content: "unused" });
		}
		assert.equal(harness.sent.length, 1);
	});

	it("resolves relative paths and emits a hidden steer with self-contained guidance", async (t) => {
		const dir = tempDir(t);
		const target = path.join(dir, "nested", "module.py");
		writeLines(target, 501);
		const harness = createHarness({ cwd: dir });

		await harness.emit("write", { path: path.join("nested", "module.py"), content: "unused" });

		assert.equal(harness.sent.length, 1);
		assert.deepEqual(harness.sent[0]?.options, { deliverAs: "steer" });
		assert.equal(harness.sent[0]?.message.customType, "basecamp-file-length-reminder");
		assert.equal(harness.sent[0]?.message.display, false);
		assert.match(harness.sent[0]?.message.content ?? "", /<system-reminder>/);
		assert.match(harness.sent[0]?.message.content ?? "", /nested\/module\.py/);
		assert.match(harness.sent[0]?.message.content ?? "", /genuine responsibility seams/);
		assert.match(harness.sent[0]?.message.content ?? "", /tighter project-specific limit/);
	});

	it("ignores failed and unrelated tools and fails open on malformed or unreadable paths", async (t) => {
		const dir = tempDir(t);
		const target = path.join(dir, "large.ts");
		writeLines(target, 351);
		const harness = createHarness();

		await harness.emit("edit", { path: target, edits: [] }, true);
		await harness.emit("read", { path: target });
		await harness.emit("edit", { path: 42, edits: [] });
		await assert.doesNotReject(() => harness.emit("write", { path: path.join(dir, "missing.py"), content: "" }));

		assert.deepEqual(harness.sent, []);
	});

	it("retries after delivery failure without affecting the edit", async (t) => {
		const dir = tempDir(t);
		const target = path.join(dir, "large.ts");
		writeLines(target, 351);
		const options: HarnessOptions = { sendError: new Error("delivery failed") };
		const harness = createHarness(options);

		await assert.doesNotReject(() => harness.emit("edit", { path: target, edits: [] }));
		assert.deepEqual(harness.sent, []);

		delete options.sendError;
		await harness.emit("edit", { path: target, edits: [] });
		assert.equal(harness.sent.length, 1);
	});

	it("suppresses repeats, re-arms under cap, and resets at settlement and session start", async (t) => {
		const dir = tempDir(t);
		const target = path.join(dir, "large.ts");
		const harness = createHarness();
		writeLines(target, 351);

		await harness.emit("edit", { path: target, edits: [] });
		await harness.emit("edit", { path: target, edits: [] });
		assert.equal(harness.sent.length, 1);

		writeLines(target, 350);
		await harness.emit("edit", { path: target, edits: [] });
		writeLines(target, 351);
		await harness.emit("edit", { path: target, edits: [] });
		assert.equal(harness.sent.length, 2);

		await harness.settle();
		await harness.emit("edit", { path: target, edits: [] });
		assert.equal(harness.sent.length, 3);

		await harness.sessionStart();
		await harness.emit("edit", { path: target, edits: [] });
		assert.equal(harness.sent.length, 4);
	});

	it("keeps mutative worker guidance aligned with the runtime policy", () => {
		const workerPrompt = fs.readFileSync(
			path.resolve(import.meta.dirname, "..", "..", "core", "swarm", "agents", "builtin", "worker.md"),
			"utf8",
		);

		for (const guidance of [
			"TypeScript/HTML 350",
			"shell 400",
			"SQL 800",
			"CSS/Python/other recognized source files 500",
			"advisory, not a gate",
		]) {
			assert.ok(workerPrompt.includes(guidance), `worker prompt should include ${guidance}`);
		}
	});
});
