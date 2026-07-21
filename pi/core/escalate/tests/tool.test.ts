import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerEscalate } from "../tool.ts";
import type { Question, QuestionAnswer } from "../types.ts";

interface ToolResult {
	content: { type: string; text: string }[];
	details: QuestionAnswer[] | null;
}

interface RegisteredTool {
	name: string;
	execute(
		toolCallId: string,
		params: { questions: Question[] },
		signal: AbortSignal | undefined,
		onUpdate: unknown,
		ctx: ExtensionContext,
	): Promise<ToolResult>;
}

interface EmittedEvent {
	channel: string;
	data: unknown;
}

class FakePi {
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};
	private tool: RegisteredTool | null = null;

	registerTool(tool: RegisteredTool): void {
		this.tool = tool;
	}

	getEscalate(): RegisteredTool {
		assert.ok(this.tool, "escalate tool should be registered");
		return this.tool;
	}
}

const questions: Question[] = [{ question: "Choose?", options: ["one", "two"] }];
const answers: QuestionAnswer[] = [{ question: "Choose?", selections: ["one"] }];
const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for user response" },
};
const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

function register(): { pi: FakePi; tool: RegisteredTool } {
	const pi = new FakePi();
	registerEscalate(pi as unknown as ExtensionAPI);
	return { pi, tool: pi.getEscalate() };
}

function contextWithCustom(custom: () => Promise<QuestionAnswer[] | null>): ExtensionContext {
	return { hasUI: true, ui: { custom } } as unknown as ExtensionContext;
}

function contextWithoutUI(): ExtensionContext {
	return { hasUI: false } as unknown as ExtensionContext;
}

describe("escalate tool", () => {
	it("marks Herdr blocked only while the interactive dialog is open", async () => {
		const { pi, tool } = register();
		const lifecycle: string[] = [];
		pi.events.emit = (channel, data) => {
			const active = (data as { active: boolean }).active;
			lifecycle.push(`${channel}:${active}`);
			pi.emitted.push({ channel, data });
		};
		const ctx = contextWithCustom(async () => {
			lifecycle.push("dialog");
			return answers;
		});

		const result = await tool.execute("call-1", { questions }, undefined, undefined, ctx);

		assert.deepEqual(lifecycle, ["herdr:blocked:true", "dialog", "herdr:blocked:false"]);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		assert.deepEqual(result.details, answers);
	});

	it("clears blocked state when the user dismisses the dialog", async () => {
		const { pi, tool } = register();

		const result = await tool.execute(
			"call-1",
			{ questions },
			undefined,
			undefined,
			contextWithCustom(async () => null),
		);

		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		assert.equal(result.content[0]?.text, "User dismissed without answering.");
		assert.equal(result.details, null);
	});

	it("clears blocked state when the dialog rejects", async () => {
		const { pi, tool } = register();
		const ctx = contextWithCustom(async () => {
			throw new Error("UI failed");
		});

		await assert.rejects(() => tool.execute("call-1", { questions }, undefined, undefined, ctx), /UI failed/);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("does not report blocked state without an interactive UI", async () => {
		const { pi, tool } = register();

		const result = await tool.execute("call-1", { questions }, undefined, undefined, contextWithoutUI());

		assert.deepEqual(pi.emitted, []);
		assert.equal(result.content[0]?.text, "[escalation] Choose?");
		assert.equal(result.details, null);
	});
});
