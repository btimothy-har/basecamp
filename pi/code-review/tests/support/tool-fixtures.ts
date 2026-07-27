/** Shared harness for the `report_findings` suites. Not a `.test.ts`, so the runner skips it. */

import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { TestContext } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Finding, ReviewScope } from "#code-review/findings.ts";
import { registerReviewTool } from "#code-review/tools.ts";
import { type Driver, paneHarness } from "./pane-driver.ts";

export interface ReviewToolResult {
	content: { type: "text"; text: string }[];
	details?: unknown;
}

export interface ReviewDetails {
	decision: string;
	counts: Record<string, number>;
	findings: number;
	annotated: boolean;
	artifactPath: string;
}

export interface RegisteredTool {
	name: string;
	execute(
		toolCallId: string,
		params: { scope: ReviewScope; summary: string; findings: Finding[] },
		signal?: AbortSignal,
		onUpdate?: unknown,
		ctx?: ExtensionContext,
	): Promise<ReviewToolResult>;
}

export interface EmittedEvent {
	channel: string;
	data: unknown;
}

export class FakePi {
	readonly tools = new Map<string, RegisteredTool>();
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};
	registerTool(tool: RegisteredTool): void {
		this.tools.set(tool.name, tool);
	}
	getReportFindings(): RegisteredTool {
		const tool = this.tools.get("report_findings");
		assert.ok(tool, "report_findings tool should be registered");
		return tool;
	}
}

export const scope: ReviewScope = {
	base: "origin/main",
	mergeBase: "abc1234",
	cwd: "/repo",
	label: "branch feature → origin/main",
};

export const summary = "Synthesized review summary.";

export const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for code-review annotation" },
};

export const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

export function finding(overrides: Partial<Finding> = {}): Finding {
	return {
		dimension: "general",
		severity: "low",
		file: null,
		lineStart: null,
		lineEnd: null,
		title: "Finding",
		detail: "Detail",
		remediation: null,
		...overrides,
	};
}

export function preserveEnv(t: TestContext, name: string): void {
	const original = process.env[name];
	t.after(() => {
		if (original === undefined) delete process.env[name];
		else process.env[name] = original;
	});
}

export function withPrimaryScratch(t: TestContext): void {
	preserveEnv(t, "BASECAMP_AGENT_DEPTH");
	preserveEnv(t, "BASECAMP_SCRATCH_DIR");
	delete process.env.BASECAMP_AGENT_DEPTH;
	process.env.BASECAMP_SCRATCH_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "code-review-tool-"));
}

export function ctxNoUI(): ExtensionContext {
	return { hasUI: false } as unknown as ExtensionContext;
}

/**
 * The pane opens one `ui.custom` view per list/card visit, so each test scripts the value every
 * view resolves with. Comment text cannot be injected here — nothing outside the component can
 * reach its store — so use `ctxWithPane` when the test needs real comment text.
 */
export function ctxWithViews(views: unknown[], onOpen: () => void = () => {}): ExtensionContext {
	const queue = [...views];
	return {
		hasUI: true,
		ui: {
			custom: async () => {
				onOpen();
				assert.ok(queue.length > 0, "pane opened more views than the test scripted");
				return queue.shift();
			},
		},
	} as unknown as ExtensionContext;
}

/** Drives the real pane components, so keystrokes reach the real store. */
export function ctxWithPane(drivers: Driver[]): ExtensionContext {
	return { hasUI: true, ui: paneHarness(drivers) } as unknown as ExtensionContext;
}

export function readArtifact(artifactPath: string): {
	json: string;
	summary: string;
	findings: (Finding & { reaction: string | null })[];
} {
	const json = fs.readFileSync(artifactPath, "utf8");
	const artifact = JSON.parse(json) as { summary: string; findings: (Finding & { reaction: string | null })[] };
	return { json, summary: artifact.summary, findings: artifact.findings };
}

export function registerHarness(): { pi: FakePi; tool: RegisteredTool } {
	const pi = new FakePi();
	registerReviewTool(pi as unknown as ExtensionAPI);
	return { pi, tool: pi.getReportFindings() };
}

export function register(): RegisteredTool {
	return registerHarness().tool;
}
