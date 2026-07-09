import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resetAgentMode, setAgentMode } from "#core/session/agent-mode.ts";
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
		model: { id: "very-long-model-name-for-layout-pressure" },
		getContextUsage: () => ({ tokens: 1000, contextWindow: 10_000, percent: 10 }),
		ui: {
			setFooter: (factory: unknown) => onFooter(factory as FooterFactory),
		},
		sessionManager: {
			getSessionId: () => "session-1",
		},
	} as unknown as ExtensionContext;
}

async function createGitCheckout(t: { after(fn: () => Promise<void> | void): void }, branch: string): Promise<string> {
	const dir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-footer-git-"));
	await fs.mkdir(path.join(dir, ".git"), { recursive: true });
	await fs.writeFile(path.join(dir, ".git", "HEAD"), `ref: refs/heads/${branch}\n`);
	t.after(async () => {
		await fs.rm(dir, { recursive: true, force: true });
	});
	return dir;
}

async function renderFooter(width: number): Promise<{ lines: string[]; dispose: () => void }> {
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
		{ fg: (_color, text) => text },
		{
			onBranchChange: () => () => {},
			getGitBranch: () => null,
			getExtensionStatuses: () => new Map(),
		},
	);
	return { lines: footer.render(width), dispose: () => footer.dispose() };
}

const originalCwd = process.cwd();

afterEach(() => {
	process.chdir(originalCwd);
	resetAgentMode();
});

describe("footer location line", () => {
	it("does not render a mode label for default executor mode", async (t) => {
		process.chdir(await createGitCheckout(t, "feature/footer-branch"));

		const footer = await renderFooter(120);
		try {
			assert.doesNotMatch(footer.lines[0]!, /\[exec\]/);
		} finally {
			footer.dispose();
		}
	});

	it("renders branch from the active git checkout even when footerData has no branch", async (t) => {
		process.chdir(await createGitCheckout(t, "feature/footer-branch"));

		const footer = await renderFooter(72);
		try {
			assert.match(footer.lines[0]!, /⎇ feature\/footer-branch/);
		} finally {
			footer.dispose();
		}
	});

	it("rerenders when mode changes away from executor", async (t) => {
		process.chdir(await createGitCheckout(t, "feature/footer-branch"));

		setAgentMode("planning");
		const footer = await renderFooter(120);
		try {
			assert.match(footer.lines[0]!, /\[explore\]/);
		} finally {
			footer.dispose();
		}
	});

	it("renders copilot mode label", async (t) => {
		process.chdir(await createGitCheckout(t, "feature/footer-branch"));

		setAgentMode("copilot");
		const footer = await renderFooter(120);
		try {
			assert.match(footer.lines[0]!, /\[copilot\]/);
		} finally {
			footer.dispose();
		}
	});
});
