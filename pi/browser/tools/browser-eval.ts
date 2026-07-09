import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
	type AgentToolResult,
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	type ExtensionAPI,
	formatSize,
	truncateHead,
} from "@earendil-works/pi-coding-agent";
import { type Static, Type } from "@sinclair/typebox";
import { getBasecampEnv, isSubagent } from "#core/platform/env.ts";
import { ensurePage } from "../browser/connection.ts";

const BrowserEvalParams = Type.Object({
	code: Type.String({
		description:
			"JavaScript async function body to execute with a puppeteer Page named `page` in scope. Use `return` to capture output.",
	}),
});

type BrowserEvalInput = Static<typeof BrowserEvalParams>;

interface BrowserEvalDetails {
	resultType: string;
	outputPath: string | null;
	outputBytes: number;
	truncated: boolean;
	truncatedBy: "lines" | "bytes" | null;
}

const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor as new (
	...args: string[]
) => (page: Awaited<ReturnType<typeof ensurePage>>) => Promise<unknown>;

function scratchDir(): string {
	return getBasecampEnv("BASECAMP_SCRATCH_DIR") ?? os.tmpdir();
}

function timestampForFile(date: Date): string {
	return date.toISOString().replace(/[:.]/g, "-");
}

function valueType(value: unknown): string {
	if (value === null) return "null";
	if (Array.isArray(value)) return "array";
	return typeof value;
}

function serializeResult(value: unknown): string {
	if (value === undefined) return "(no value returned)";
	try {
		const serialized = JSON.stringify(value, null, 2);
		return serialized === undefined ? String(value) : serialized;
	} catch {
		return String(value);
	}
}

async function writeFullOutput(text: string): Promise<string> {
	const outputDir = path.join(scratchDir(), "browser");
	await fs.mkdir(outputDir, { recursive: true });
	const outputPath = path.join(outputDir, `browser-eval-${timestampForFile(new Date())}.txt`);
	await fs.writeFile(outputPath, text, { encoding: "utf8", mode: 0o600 });
	return outputPath;
}

async function buildOutputText(
	rawText: string,
): Promise<{ text: string; outputPath: string | null; truncated: boolean; truncatedBy: "lines" | "bytes" | null }> {
	const truncation = truncateHead(rawText, { maxBytes: DEFAULT_MAX_BYTES, maxLines: DEFAULT_MAX_LINES });
	if (!truncation.truncated) {
		return { text: truncation.content, outputPath: null, truncated: false, truncatedBy: null };
	}

	const outputPath = await writeFullOutput(rawText);
	const pointer = `\n\n[Output truncated to ${formatSize(truncation.outputBytes)}. Full output (${formatSize(
		truncation.totalBytes,
	)}) written to ${outputPath}]`;
	return {
		text: `${truncation.content}${pointer}`,
		outputPath,
		truncated: true,
		truncatedBy: truncation.truncatedBy,
	};
}

export function registerBrowserEvalTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "browser_eval",
		label: "Browser Eval",
		description:
			"Run JavaScript in a real headed Chrome/Brave browser over Chrome DevTools Protocol. " +
			"The browser keeps the user's persistent Basecamp profile. `page` is a puppeteer Page in scope; use `await page.goto(url)` to navigate, puppeteer methods to click/type/extract, and `return` a value to capture output. One call can navigate, interact, and extract.",
		promptSnippet: "Run JavaScript against a headed Chrome/Brave browser with a puppeteer Page named page",
		promptGuidelines: [
			"browser_eval executes an async JavaScript function body with `page` in scope as a puppeteer Page.",
			"Use `await page.goto(url)` for navigation, then `await page.evaluate(...)`, `click`, `type`, and other puppeteer APIs as needed.",
			"Use `return` to capture a JSON-serializable value. A single call can navigate, interact, and extract data.",
			"The headed browser uses the user's persistent Basecamp Chrome/Brave profile.",
		],
		parameters: BrowserEvalParams,

		async execute(_id, params: BrowserEvalInput): Promise<AgentToolResult<BrowserEvalDetails>> {
			if (isSubagent()) throw new Error("browser tools are main-session only; not available to subagents");

			const page = await ensurePage();
			const fn = new AsyncFunction("page", params.code);
			const result = await fn(page);
			const rawText = serializeResult(result);
			const output = await buildOutputText(rawText);

			return {
				details: {
					resultType: valueType(result),
					outputPath: output.outputPath,
					outputBytes: Buffer.byteLength(rawText, "utf8"),
					truncated: output.truncated,
					truncatedBy: output.truncatedBy,
				},
				content: [{ type: "text", text: output.text }],
			};
		},
	});
}
