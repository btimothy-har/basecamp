import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { registerFooter } from "../footer.ts";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

type FooterFactory = (
	tui: { requestRender(): void },
	theme: { fg: ThemeFg },
	footerData: {
		onBranchChange(listener: () => void): () => void;
		getGitBranch(): string | null;
		getExtensionStatuses(): Map<string, string>;
	},
) => { render(width: number): string[]; dispose(): void };

function createPi() {
	const handlers = new Map<string, (event: unknown, ctx: ExtensionContext) => Promise<void> | void>();
	const pi = {
		on: (event: string, handler: (event: unknown, ctx: ExtensionContext) => Promise<void> | void) => {
			handlers.set(event, handler);
		},
		getThinkingLevel: () => "medium",
	} as unknown as ExtensionAPI;

	return { pi, handlers };
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

const fg: ThemeFg = (_color, text) => text;

describe("footer extension statuses", () => {
	it("renders extension statuses on line 3", async () => {
		const footerFactoryRef: { current: FooterFactory | null } = { current: null };
		const { pi, handlers } = createPi();
		const ctx = createContext((factory) => {
			footerFactoryRef.current = factory;
		});
		registerFooter(pi);

		await handlers.get("session_start")?.({}, ctx);
		const footerFactory = footerFactoryRef.current;
		assert.ok(footerFactory);

		const footer = footerFactory(
			{ requestRender: () => {} },
			{ fg },
			{
				onBranchChange: () => () => {},
				getGitBranch: () => "main",
				getExtensionStatuses: () =>
					new Map([
						["b", "agent b"],
						["a", "agent a"],
					]),
			},
		);

		const lines = footer.render(160);
		assert.equal(lines[2], "agent a  agent b");
		footer.dispose();
	});

	it("renders empty line 3 when no extension statuses are present", async () => {
		const footerFactoryRef: { current: FooterFactory | null } = { current: null };
		const { pi, handlers } = createPi();
		const ctx = createContext((factory) => {
			footerFactoryRef.current = factory;
		});
		registerFooter(pi);

		await handlers.get("session_start")?.({}, ctx);
		const footerFactory = footerFactoryRef.current;
		assert.ok(footerFactory);

		const footer = footerFactory(
			{ requestRender: () => {} },
			{ fg },
			{
				onBranchChange: () => () => {},
				getGitBranch: () => "main",
				getExtensionStatuses: () => new Map(),
			},
		);

		const lines = footer.render(120);
		assert.equal(lines[2], "");
		footer.dispose();
	});
});
