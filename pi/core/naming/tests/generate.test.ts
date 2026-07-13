import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ADJECTIVES, NAME_BANK, NOUNS } from "../bank.ts";
import { ADJ_ADJ_NOUN, ADJ_NOUN, generateName } from "../generate.ts";

function sequenceRng(values: number[]): () => number {
	let index = 0;
	return () => {
		const value = values[index];
		index += 1;
		if (value === undefined) {
			throw new Error("rng sequence exhausted");
		}
		return value;
	};
}

describe("word bank", () => {
	it("has unique lowercase-letter words with adjectives and nouns disjoint", () => {
		assert.equal(new Set(NAME_BANK).size, NAME_BANK.length);
		assert.equal(NAME_BANK.length, ADJECTIVES.length + NOUNS.length);
		for (const word of NAME_BANK) {
			assert.match(word, /^[a-z]{2,}$/);
		}
	});

	it("keeps the adjective-adjective-noun namespace comfortable", () => {
		// ~50% collision odds sit near 1.18 * sqrt(namespace); >1M keeps headroom for many slugs.
		const namespace = ADJECTIVES.length * (ADJECTIVES.length - 1) * NOUNS.length;
		assert.ok(namespace >= 1_000_000, `expected at least 1M combinations, got ${namespace}`);
	});
});

describe("generateName", () => {
	it("defaults to adjective-adjective-noun with two distinct adjectives", () => {
		const name = generateName({ rng: sequenceRng([0, 0, 0]) });
		const [first, second, third] = name.split("-");

		assert.match(name, /^[a-z]+-[a-z]+-[a-z]+$/);
		assert.ok(ADJECTIVES.includes(first ?? ""));
		assert.ok(ADJECTIVES.includes(second ?? ""));
		assert.notEqual(first, second);
		assert.ok(NOUNS.includes(third ?? ""));
	});

	it("builds adjective-noun for handle-style callers", () => {
		const name = generateName({ pattern: ADJ_NOUN, rng: sequenceRng([0, 0]) });
		const [first, second] = name.split("-");

		assert.match(name, /^[a-z]+-[a-z]+$/);
		assert.ok(ADJECTIVES.includes(first ?? ""));
		assert.ok(NOUNS.includes(second ?? ""));
	});

	it("uses injected rng deterministically", () => {
		const first = generateName({ pattern: ADJ_ADJ_NOUN, rng: sequenceRng([0, 0, 0]) });
		const second = generateName({ pattern: ADJ_ADJ_NOUN, rng: sequenceRng([0, 0, 0]) });

		assert.equal(first, `${ADJECTIVES[0]}-${ADJECTIVES[1]}-${NOUNS[0]}`);
		assert.equal(second, first);
	});

	it("regenerates when a candidate is already taken", () => {
		const firstName = `${ADJECTIVES[0]}-${ADJECTIVES[1]}-${NOUNS[0]}`;
		const taken = new Set([firstName]);
		const seen: string[] = [];
		const name = generateName({
			rng: sequenceRng([0, 0, 0, 0.4, 0.4, 0.4]),
			isTaken(candidate) {
				seen.push(candidate);
				return taken.has(candidate);
			},
		});

		assert.deepEqual(seen, [firstName, name]);
		assert.notEqual(name, firstName);
		assert.equal(taken.has(name), false);
	});

	it("throws when attempts are exhausted", () => {
		assert.throws(
			() =>
				generateName({
					rng: sequenceRng([0, 0, 0, 0, 0, 0]),
					isTaken: () => true,
					maxAttempts: 2,
				}),
			/Unable to generate an available name after 2 attempts/,
		);
	});

	it("rejects an rng outside the [0, 1) range", () => {
		assert.throws(() => generateName({ rng: () => 1 }), /range \[0, 1\)/);
	});
});
