/**
 * Whole-graph load + registration test.
 *
 * Importing the composition root pulls in every context module under strict
 * Node semantics (explicit .ts extensions, erasable-syntax-only TypeScript) —
 * guarding against imports that only Pi's more lenient loader would accept.
 * Registration runs against a permissive ExtensionAPI stand-in; extension.ts
 * degrades failing modules via console.error, so any degradation fails here.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import register from "./extension.ts";

function makeStub(): unknown {
	const fn = () => makeStub();
	return new Proxy(fn, {
		get(_target, prop) {
			if (typeof prop === "symbol") return undefined;
			if (prop === "then") return undefined; // don't look thenable
			return makeStub();
		},
	});
}

test("every module registers without degradation", () => {
	const degradations: unknown[][] = [];
	const originalError = console.error;
	console.error = (...args: unknown[]) => {
		degradations.push(args);
	};
	try {
		register(makeStub() as Parameters<typeof register>[0]);
	} finally {
		console.error = originalError;
	}
	assert.deepEqual(
		degradations.map((args) => args[0]),
		[],
	);
});
