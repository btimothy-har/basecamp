import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { AgentToolResult, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import type { Page } from "puppeteer-core";
import { getBasecampEnv, isSubagent } from "#core/platform/env.ts";
import { ensurePage } from "../browser/connection.ts";

const BrowserScreenshotParams = Type.Object({
	fullPage: Type.Optional(Type.Boolean({ description: "Capture the full scrollable page. Defaults to false." })),
	selector: Type.Optional(
		Type.String({ description: "CSS selector for an element to screenshot instead of the page." }),
	),
});

type BrowserScreenshotInput = Static<typeof BrowserScreenshotParams>;

interface ScreenshotDimensions {
	width: number;
	height: number;
}

interface BrowserScreenshotDetails {
	path: string;
	mimeType: "image/png";
	bytes: number;
	fullPage: boolean;
	selector: string | null;
	dimensions: ScreenshotDimensions | null;
}

function scratchDir(): string {
	return getBasecampEnv("BASECAMP_SCRATCH_DIR") ?? os.tmpdir();
}

function timestampForFile(date: Date): string {
	return date.toISOString().replace(/[:.]/g, "-");
}

async function screenshotPath(): Promise<string> {
	const outputDir = path.join(scratchDir(), "browser");
	await fs.mkdir(outputDir, { recursive: true });
	return path.join(outputDir, `browser-screenshot-${timestampForFile(new Date())}.png`);
}

async function pageDimensions(page: Page, fullPage: boolean): Promise<ScreenshotDimensions | null> {
	if (!fullPage) {
		const viewport = page.viewport();
		return viewport ? { width: viewport.width, height: viewport.height } : null;
	}

	return await page.evaluate(() => {
		const doc = (
			globalThis as unknown as {
				document: {
					documentElement: { scrollWidth: number; scrollHeight: number };
					body?: { scrollWidth: number; scrollHeight: number } | null;
				};
			}
		).document;
		return {
			width: Math.max(doc.documentElement.scrollWidth, doc.body?.scrollWidth ?? 0),
			height: Math.max(doc.documentElement.scrollHeight, doc.body?.scrollHeight ?? 0),
		};
	});
}

export function registerBrowserScreenshotTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "browser_screenshot",
		label: "Browser Screenshot",
		description:
			"Capture a PNG screenshot from the persistent headed Chrome/Brave browser. " +
			"Capture the current viewport, the full page, or a CSS selector element; returns both an inline image and a saved scratch file path.",
		promptSnippet: "Capture a PNG screenshot from the current headed Chrome/Brave browser page",
		promptGuidelines: [
			"Use browser_screenshot after browser_eval navigation or interaction to inspect the headed Chrome/Brave page.",
			"Set selector to capture a specific element, or fullPage true to capture the full scrollable page.",
			"The result includes an inline PNG image and a saved file path in scratch space.",
		],
		parameters: BrowserScreenshotParams,

		async execute(_id, params: BrowserScreenshotInput): Promise<AgentToolResult<BrowserScreenshotDetails>> {
			if (isSubagent()) throw new Error("browser tools are main-session only; not available to subagents");

			const page = await ensurePage();
			const selector = params.selector?.trim() || null;
			const fullPage = params.fullPage === true;
			let dimensions: ScreenshotDimensions | null = null;
			let png: Uint8Array;

			if (selector) {
				const element = await page.$(selector);
				if (!element) throw new Error(`No element found for selector: ${selector}`);
				const box = await element.boundingBox();
				dimensions = box ? { width: Math.round(box.width), height: Math.round(box.height) } : null;
				png = await element.screenshot({ type: "png" });
			} else {
				dimensions = await pageDimensions(page, fullPage);
				png = await page.screenshot({ type: "png", fullPage });
			}

			const outputPath = await screenshotPath();
			await fs.writeFile(outputPath, png, { mode: 0o600 });
			const data = Buffer.from(png).toString("base64");

			return {
				details: {
					path: outputPath,
					mimeType: "image/png",
					bytes: png.byteLength,
					fullPage,
					selector,
					dimensions,
				},
				content: [
					{ type: "image", data, mimeType: "image/png" },
					{ type: "text", text: `Screenshot saved to ${outputPath}` },
				],
			};
		},
	});
}
