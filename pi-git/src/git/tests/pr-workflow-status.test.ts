import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { initializeCurrentSessionState, resetCurrentSessionState } from "pi-core/state/index.ts";
import {
	clearActivePR,
	getActivePR,
	lockAll,
	publishActivePRStatus,
	registerGuards,
	renderActivePRStatus,
	setActivePR,
	unlocked,
} from "../guards.ts";

type StatusSetCall = {
	key: string;
	value: string | undefined;
};

type Theme = (color: string, text: string) => string;
type Handler = (event: unknown, ctx: ExtensionContext) => Promise<unknown>;

const SESSION_ID = "pr-workflow-status-test";
const SESSION_FILE = "/tmp/pr-workflow-status-test.jsonl";

let tempDir: string;

function createContext(calls: StatusSetCall[], hasUI = true): ExtensionContext {
	const fg: Theme = (color, text) => `${color}:${text}`;
	return {
		hasUI,
		sessionManager: {
			getSessionId: () => SESSION_ID,
			getSessionFile: () => SESSION_FILE,
			getHeader: () => ({
				type: "session",
				version: 3,
				id: SESSION_ID,
				timestamp: "2026-01-01T00:00:00.000Z",
				cwd: "/tmp",
			}),
		},
		ui: {
			theme: { fg },
			setStatus: (key: string, value: string | undefined) => {
				calls.push({ key, value });
			},
		},
	} as unknown as ExtensionContext;
}

function createFakePi(handlers: Map<string, Handler>): ExtensionAPI {
	return {
		on(name: string, handler: Handler) {
			handlers.set(name, handler);
		},
	} as unknown as ExtensionAPI;
}

function registerAndGetSessionStartHandler(): Handler {
	const handlers = new Map<string, Handler>();
	registerGuards(createFakePi(handlers));
	const handler = handlers.get("session_start");
	assert.ok(handler);
	return handler;
}

describe("PR workflow status", () => {
	beforeEach(async () => {
		tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "pi-git-pr-workflow-status-"));
		initializeCurrentSessionState(createContext([]), tempDir);
		unlocked.prComment = true;
		lockAll();
	});

	afterEach(async () => {
		resetCurrentSessionState();
		await fs.rm(tempDir, { recursive: true, force: true });
	});

	it("formats active PR workflow status", () => {
		const fg: Theme = (color, text) => `${color}:${text}`;

		assert.equal(renderActivePRStatus(fg, { number: "167", base: "main" }), "accent:PR success:#167 dim:→ main");
	});

	it("publishes and clears active PR workflow status", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls);

		setActivePR({ number: "167", base: "main" }, ctx);
		assert.deepEqual(getActivePR(), { number: "167", base: "main" });
		assert.deepEqual(calls, [{ key: "basecamp.prWorkflow", value: "accent:PR success:#167 dim:→ main" }]);

		clearActivePR(ctx);
		assert.equal(getActivePR(), null);
		assert.deepEqual(calls.at(-1), { key: "basecamp.prWorkflow", value: undefined });
	});

	it("keeps active PR workflow status when workflow locks reset", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls);
		setActivePR({ number: "167", base: "main" }, ctx);
		unlocked.prComment = true;

		lockAll();

		assert.deepEqual(getActivePR(), { number: "167", base: "main" });
		assert.equal(unlocked.prComment, false);
		assert.deepEqual(calls.at(-1), { key: "basecamp.prWorkflow", value: "accent:PR success:#167 dim:→ main" });
	});

	it("republishes active PR workflow status on session start", async () => {
		const handler = registerAndGetSessionStartHandler();
		const calls: StatusSetCall[] = [];
		setActivePR({ number: "187", base: "main" });

		await handler({}, createContext(calls));

		assert.deepEqual(calls, [{ key: "basecamp.prWorkflow", value: "accent:PR success:#187 dim:→ main" }]);
	});

	it("clears active PR workflow status on session start without active PR", async () => {
		const handler = registerAndGetSessionStartHandler();
		const calls: StatusSetCall[] = [];
		assert.equal(getActivePR(), null);

		await handler({}, createContext(calls));

		assert.deepEqual(calls, [{ key: "basecamp.prWorkflow", value: undefined }]);
	});

	it("no-ops status publishing without UI", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls, false);

		publishActivePRStatus(ctx, { number: "167", base: "main" });
		publishActivePRStatus(undefined, { number: "167", base: "main" });

		assert.deepEqual(calls, []);
	});
});
