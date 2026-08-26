import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { type Component, visibleWidth } from "@earendil-works/pi-tui";
import {
	escapePromptForDisplay,
	type SystemPromptPreview,
	SystemPromptViewer,
	showSystemPromptPreview,
} from "#system-prompt/viewer.ts";

const theme = {
	bold: (text: string) => text,
	fg: (_color: string, text: string) => text,
} as unknown as ConstructorParameters<typeof SystemPromptViewer>[1];

function createViewer(preview: SystemPromptPreview, rows = 13) {
	let renders = 0;
	let closes = 0;
	const copies: string[] = [];
	const viewer = new SystemPromptViewer(
		preview,
		theme,
		() => rows,
		() => renders++,
		() => closes++,
		() => copies.push(preview.prompt),
	);
	return {
		viewer,
		get renders() {
			return renders;
		},
		get closes() {
			return closes;
		},
		copies,
	};
}

function renderedText(component: Component, width = 60): string {
	return component.render(width).join("\n");
}

async function settleCopy(): Promise<void> {
	await new Promise<void>((resolve) => setImmediate(resolve));
}

function previewContext(notices: Array<{ message: string; level?: string }>) {
	let component: Component | undefined;
	const ctx = {
		ui: {
			custom: async (factory: (...args: unknown[]) => Component) => {
				component = factory({ terminal: { rows: 20 }, requestRender() {} }, theme, {}, () => {});
			},
			notify(message: string, level?: string) {
				notices.push({ message, level });
			},
		},
	} as unknown as ExtensionCommandContext;
	return { ctx, getComponent: () => component };
}

describe("escapePromptForDisplay", () => {
	it("renders terminal controls visibly while preserving line feeds", () => {
		assert.equal(escapePromptForDisplay("plain\n\x1b[31mred\t\r\0\u009b"), "plain\n\\x1b[31mred\\t\\r\\x00\\x9b");
	});
});

describe("SystemPromptViewer", () => {
	it("pages through the complete wrapped prompt with bounded navigation", () => {
		const prompt = Array.from({ length: 8 }, (_, index) => `line-${index + 1}`).join("\n");
		const harness = createViewer({ prompt, inactive: false });

		let output = renderedText(harness.viewer, 40);
		assert.match(output, /line-1/);
		assert.match(output, /line-3/);
		assert.doesNotMatch(output, /line-4/);

		harness.viewer.handleInput("\x1b[B");
		assert.match(renderedText(harness.viewer, 40), /Visual lines 2-4 of 8/);
		harness.viewer.handleInput("\x1b[A");
		assert.match(renderedText(harness.viewer, 40), /Visual lines 1-3 of 8/);

		harness.viewer.handleInput("\x1b[6~");
		output = renderedText(harness.viewer, 40);
		assert.match(output, /line-4/);
		assert.match(output, /line-6/);
		assert.doesNotMatch(output, /line-7/);
		harness.viewer.handleInput("\x1b[5~");
		assert.match(renderedText(harness.viewer, 40), /Visual lines 1-3 of 8/);
		harness.viewer.handleInput("\x1b[6~");

		harness.viewer.handleInput("\x1b[F");
		output = renderedText(harness.viewer, 40);
		assert.match(output, /line-8/);
		assert.match(output, /Visual lines 6-8 of 8/);

		harness.viewer.handleInput("\x1b[H");
		assert.match(renderedText(harness.viewer, 40), /Visual lines 1-3 of 8/);
		assert.equal(harness.renders, 7);
	});

	it("reflows safely on narrow terminals and distinguishes inactive previews", () => {
		const harness = createViewer({ prompt: "one very long source line", inactive: true }, 14);
		const lines = harness.viewer.render(12);

		assert.ok(lines.every((line) => visibleWidth(line) <= 12));
		assert.match(lines.join("\n"), /Inactive/);
		assert.match(lines.join("\n"), /one very/);
		assert.match(lines.join("\n"), /line/);
	});

	it("copies the exact raw prompt only on request and closes on Escape", () => {
		const prompt = "raw\x1b\tcontent";
		const harness = createViewer({ prompt, inactive: false });
		harness.viewer.render(40);
		assert.deepEqual(harness.copies, []);

		harness.viewer.handleInput("c");
		harness.viewer.handleInput("\x1b");

		assert.deepEqual(harness.copies, [prompt]);
		assert.equal(harness.closes, 1);
	});
});

describe("showSystemPromptPreview", () => {
	it("reports clipboard success after copying the exact raw prompt", async () => {
		const notices: Array<{ message: string; level?: string }> = [];
		const { ctx, getComponent } = previewContext(notices);
		const prompt = "raw\x1b prompt";
		let copied: string | undefined;
		await showSystemPromptPreview({ prompt, inactive: false }, ctx, async (text) => {
			copied = text;
		});
		assert.equal(copied, undefined);

		getComponent()?.handleInput?.("c");
		await settleCopy();

		assert.equal(copied, prompt);
		assert.deepEqual(notices, [{ message: "System prompt copied.", level: "info" }]);
	});

	it("keeps clipboard failures user-visible", async () => {
		const notices: Array<{ message: string; level?: string }> = [];
		const { ctx, getComponent } = previewContext(notices);
		await showSystemPromptPreview({ prompt: "prompt", inactive: false }, ctx, async () => {
			throw new Error("clipboard unavailable");
		});

		getComponent()?.handleInput?.("c");
		await settleCopy();

		assert.deepEqual(notices, [{ message: "Could not copy system prompt: clipboard unavailable", level: "error" }]);
	});
});
