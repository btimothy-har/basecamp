import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import { resetDaemonStatusForTesting, setDaemonStatus } from "../../platform/daemon-status.ts";
import { registerFooter, renderDaemonStatus } from "../ui/footer.ts";

const fg: Parameters<typeof renderDaemonStatus>[0] = (_color, text) => text;

type FooterFactory = (
	tui: { requestRender(): void },
	theme: { fg: Parameters<typeof renderDaemonStatus>[0] },
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

describe("footer daemon status", () => {
	beforeEach(() => resetDaemonStatusForTesting());

	it("renders compact lifecycle labels", () => {
		assert.equal(renderDaemonStatus(fg, { kind: "idle" }), "daemon idle");
		assert.equal(renderDaemonStatus(fg, { kind: "starting" }), "daemon … starting");
		assert.equal(renderDaemonStatus(fg, { kind: "connected" }), "daemon ✓ connected");
		assert.equal(renderDaemonStatus(fg, { kind: "disconnected" }), "daemon ⚠ disconnected");
	});

	it("renders unavailable reason safely", () => {
		assert.equal(
			renderDaemonStatus(fg, { kind: "unavailable", message: "first\nsecond\tthird" }),
			"daemon ✗ first second third",
		);
	});

	it("truncates long unavailable reasons", () => {
		const rendered = renderDaemonStatus(fg, { kind: "unavailable", message: "x".repeat(120) });

		assert.ok(rendered.includes("…"));
		assert.equal(visibleWidth(rendered), "daemon ✗ ".length + 80);
	});

	it("renders daemon status before extension statuses on line 3", async () => {
		const footerFactoryRef: { current: FooterFactory | null } = { current: null };
		const { pi, handlers } = createPi();
		const ctx = createContext((factory) => {
			footerFactoryRef.current = factory;
		});
		registerFooter(pi);

		await handlers.get("session_start")?.({}, ctx);
		const footerFactory = footerFactoryRef.current;
		assert.ok(footerFactory);

		let renderRequests = 0;
		const footer = footerFactory(
			{ requestRender: () => renderRequests++ },
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

		setDaemonStatus({ kind: "connected" });
		const lines = footer.render(160);

		assert.equal(renderRequests, 1);
		assert.equal(lines.length, 3);
		assert.equal(lines[2], "daemon ✓ connected  agent a  agent b");
		footer.dispose();
	});
});
