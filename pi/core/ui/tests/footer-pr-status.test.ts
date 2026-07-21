import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { hyperlink, resetCapabilitiesCache, setCapabilities, visibleWidth } from "@earendil-works/pi-tui";
import { registerFooter } from "../footer.ts";

type ThemeColor = Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0];
type ThemeFg = (color: ThemeColor, text: string) => string;

type FooterFactory = (
	tui: { requestRender(): void },
	theme: { fg: ThemeFg },
	footerData: {
		onBranchChange(listener: () => void): () => void;
		getGitBranch(): string | null;
		getExtensionStatuses(): Map<string, string>;
	},
) => { render(width: number): string[]; dispose(): void };

interface PrResponse {
	number: number;
	url: string;
	state: "OPEN" | "MERGED" | "CLOSED";
	isDraft: boolean;
}

interface FooterHarness {
	ctx: ExtensionContext;
	handlers: Map<string, (event: unknown, ctx: ExtensionContext) => Promise<void> | void>;
	execCalls: number;
	fgCalls: Array<{ color: ThemeColor; text: string }>;
	requestRenders: number;
	render(width: number): string[];
	dispose(): void;
}

const originalCwd = process.cwd();

afterEach(() => {
	process.chdir(originalCwd);
	resetCapabilitiesCache();
});

async function createCheckout(t: { after(fn: () => Promise<void> | void): void }): Promise<string> {
	const directory = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-footer-pr-"));
	await fs.mkdir(path.join(directory, ".git"), { recursive: true });
	await fs.writeFile(path.join(directory, ".git", "HEAD"), "ref: refs/heads/feature/footer-pr\n");
	t.after(() => fs.rm(directory, { recursive: true, force: true }));
	return directory;
}

function execResult(response: PrResponse | null) {
	return response
		? { code: 0, stdout: JSON.stringify(response), stderr: "", killed: false }
		: { code: 1, stdout: "", stderr: "no pull requests found", killed: false };
}

function createContext(onFooter: (factory: FooterFactory) => void): ExtensionContext {
	return {
		hasUI: true,
		model: { id: "test-model" },
		getContextUsage: () => ({ tokens: 1000, contextWindow: 10_000, percent: 10 }),
		ui: {
			setFooter: (factory: unknown) => onFooter(factory as FooterFactory),
		},
		sessionManager: {
			getSessionId: () => "session-1",
		},
	} as unknown as ExtensionContext;
}

async function createFooterHarness(
	t: { after(fn: () => Promise<void> | void): void },
	responses: Array<PrResponse | null>,
	statuses = new Map<string, string>(),
): Promise<FooterHarness> {
	process.chdir(await createCheckout(t));
	const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => Promise<void> | void>();
	const footerFactoryRef: { current: FooterFactory | null } = { current: null };
	let execCalls = 0;
	const pi = {
		on: (event: string, handler: (event: unknown, ctx: ExtensionContext) => Promise<void> | void) => {
			handlers.set(event, handler);
		},
		exec: (command: string, args: string[]) => {
			assert.equal(command, "gh");
			assert.deepEqual(args, ["pr", "view", "--json", "number,url,state,isDraft"]);
			const response = responses[Math.min(execCalls, responses.length - 1)] ?? null;
			execCalls += 1;
			return Promise.resolve(execResult(response));
		},
		getThinkingLevel: () => "medium",
	} as unknown as ExtensionAPI;
	const ctx = createContext((factory) => {
		footerFactoryRef.current = factory;
	});
	registerFooter(pi);
	await handlers.get("session_start")?.({}, ctx);
	const footerFactory = footerFactoryRef.current;
	assert.ok(footerFactory);

	let requestRenders = 0;
	const fgCalls: FooterHarness["fgCalls"] = [];
	const footer = footerFactory(
		{
			requestRender: () => {
				requestRenders += 1;
			},
		},
		{
			fg: (color: ThemeColor, text: string) => {
				fgCalls.push({ color, text });
				return text;
			},
		},
		{
			onBranchChange: () => () => {},
			getGitBranch: () => "feature/footer-pr",
			getExtensionStatuses: () => statuses,
		},
	);
	t.after(() => footer.dispose());
	await settle();

	return {
		ctx,
		handlers,
		get execCalls() {
			return execCalls;
		},
		fgCalls,
		get requestRenders() {
			return requestRenders;
		},
		render: (width) => footer.render(width),
		dispose: () => footer.dispose(),
	};
}

async function settle(): Promise<void> {
	await new Promise<void>((resolve) => setImmediate(resolve));
}

function pr(number: number, state: PrResponse["state"], isDraft = false): PrResponse {
	return {
		number,
		url: `https://github.com/example/basecamp/pull/${number}`,
		state,
		isDraft,
	};
}

describe("footer pull request status", () => {
	it("maps every pull request state to its glyph and theme role", async (t) => {
		const cases = [
			{ response: pr(1, "OPEN"), label: "● PR #1", color: "success" },
			{ response: pr(2, "OPEN", true), label: "○ PR #2", color: "muted" },
			{ response: pr(3, "MERGED"), label: "◆ PR #3", color: "accent" },
			{ response: pr(4, "CLOSED"), label: "× PR #4", color: "error" },
		] as const;

		for (const expected of cases) {
			await t.test(expected.response.state.toLowerCase() + (expected.response.isDraft ? " draft" : ""), async (t) => {
				setCapabilities({ images: null, trueColor: true, hyperlinks: false });
				const harness = await createFooterHarness(t, [expected.response]);
				const line = harness.render(30)[2]!;

				assert.ok(line.endsWith(expected.label));
				assert.ok(harness.fgCalls.some((call) => call.color === expected.color && call.text === expected.label));
			});
		}
	});

	it("keeps sorted statuses left and links the whole right-aligned PR segment", async (t) => {
		setCapabilities({ images: null, trueColor: true, hyperlinks: true });
		const response = pr(297, "OPEN");
		const statuses = new Map([
			["b", "agent b"],
			["a", "agent a"],
		]);
		const harness = await createFooterHarness(t, [response], statuses);

		const line = harness.render(60)[2]!;

		assert.ok(line.startsWith("agent a  agent b"));
		assert.ok(line.endsWith(hyperlink("● PR #297", response.url)));
		assert.equal(visibleWidth(line), 60);
	});

	it("renders plain PR text when terminal hyperlinks are unavailable", async (t) => {
		setCapabilities({ images: null, trueColor: true, hyperlinks: false });
		const response = pr(297, "OPEN");
		const harness = await createFooterHarness(t, [response]);

		const line = harness.render(30)[2]!;

		assert.ok(line.endsWith("● PR #297"));
		assert.equal(line.includes(response.url), false);
		assert.equal(line.includes("\u001b]8;;"), false);
	});

	it("uses only complete linked candidates at narrow widths", async (t) => {
		setCapabilities({ images: null, trueColor: true, hyperlinks: true });
		const response = pr(297, "OPEN");
		const harness = await createFooterHarness(t, [response], new Map([["status", "long running status"]]));

		const full = harness.render(9)[2]!;
		const compact = harness.render(8)[2]!;
		const minimal = harness.render(4)[2]!;
		const hidden = harness.render(3)[2]!;

		assert.equal(full, hyperlink("● PR #297", response.url));
		assert.equal(compact, ` ${hyperlink("PR #297", response.url)}`);
		assert.equal(minimal, hyperlink("#297", response.url));
		assert.equal(hidden.includes(response.url), false);
		assert.equal(visibleWidth(hidden), 3);
	});

	it("preserves the existing status row when no PR is associated", async (t) => {
		setCapabilities({ images: null, trueColor: true, hyperlinks: true });
		const statuses = new Map([
			["b", "agent b"],
			["a", "agent a"],
		]);
		const withStatuses = await createFooterHarness(t, [null], statuses);
		assert.equal(withStatuses.render(120)[2], "agent a  agent b");

		const empty = await createFooterHarness(t, [null]);
		assert.equal(empty.render(120)[2], "");
	});

	it("refreshes and rerenders after the agent settles", async (t) => {
		setCapabilities({ images: null, trueColor: true, hyperlinks: false });
		const harness = await createFooterHarness(t, [pr(1, "OPEN"), pr(2, "MERGED")]);
		assert.ok(harness.render(30)[2]!.endsWith("● PR #1"));
		const rendersBeforeRefresh = harness.requestRenders;

		await harness.handlers.get("agent_settled")?.({ type: "agent_settled" }, harness.ctx);
		await settle();

		assert.equal(harness.execCalls, 2);
		assert.ok(harness.render(30)[2]!.endsWith("◆ PR #2"));
		assert.ok(harness.requestRenders > rendersBeforeRefresh);
	});
});
