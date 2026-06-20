import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
	activePR,
	clearActivePR,
	lockAll,
	publishActivePRStatus,
	renderActivePRStatus,
	setActivePR,
} from "../guards.ts";

type StatusSetCall = {
	key: string;
	value: string | undefined;
};

type Theme = (color: string, text: string) => string;

function createContext(calls: StatusSetCall[], hasUI = true): ExtensionContext {
	const fg: Theme = (color, text) => `${color}:${text}`;
	return {
		hasUI,
		ui: {
			theme: { fg },
			setStatus: (key: string, value: string | undefined) => {
				calls.push({ key, value });
			},
		},
	} as unknown as ExtensionContext;
}

describe("PR workflow status", () => {
	beforeEach(() => {
		lockAll();
	});

	it("formats active PR workflow status", () => {
		const fg: Theme = (color, text) => `${color}:${text}`;

		assert.equal(renderActivePRStatus(fg, { number: "167", base: "main" }), "accent:PR success:#167 dim:→ main");
	});

	it("publishes and clears active PR workflow status", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls);

		setActivePR({ number: "167", base: "main" }, ctx);
		assert.deepEqual(activePR, { number: "167", base: "main" });
		assert.deepEqual(calls, [{ key: "basecamp.prWorkflow", value: "accent:PR success:#167 dim:→ main" }]);

		clearActivePR(ctx);
		assert.equal(activePR, null);
		assert.deepEqual(calls.at(-1), { key: "basecamp.prWorkflow", value: undefined });
	});

	it("clears footer status when workflow locks reset", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls);
		setActivePR({ number: "167", base: "main" }, ctx);

		lockAll(ctx);

		assert.equal(activePR, null);
		assert.deepEqual(calls.at(-1), { key: "basecamp.prWorkflow", value: undefined });
	});

	it("no-ops status publishing without UI", () => {
		const calls: StatusSetCall[] = [];
		const ctx = createContext(calls, false);

		publishActivePRStatus(ctx, { number: "167", base: "main" });
		publishActivePRStatus(undefined, { number: "167", base: "main" });

		assert.deepEqual(calls, []);
	});
});
