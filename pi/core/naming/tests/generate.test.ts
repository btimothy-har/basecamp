import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { NAME_BANK } from "../bank.ts";
import { generateName } from "../generate.ts";

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

describe("NAME_BANK", () => {
	it("contains only unique lowercase-letter words", () => {
		assert.equal(new Set(NAME_BANK).size, NAME_BANK.length);
		for (const word of NAME_BANK) {
			assert.match(word, /^[a-z]{2,}$/);
		}
	});

	it("is large enough to keep the three-word namespace comfortable", () => {
		assert.ok(NAME_BANK.length >= 150, `expected at least 150 words, got ${NAME_BANK.length}`);
	});
});

describe("generateName", () => {
	it("defaults to three distinct lowercase hyphen-joined words matching safe label rules", () => {
		const name = generateName({ rng: sequenceRng([0, 0, 0]) });
		const words = name.split("-");

		assert.match(name, /^[A-Za-z0-9][A-Za-z0-9._-]*$/);
		assert.match(name, /^[a-z]+-[a-z]+-[a-z]+$/);
		assert.equal(words.length, 3);
		assert.equal(new Set(words).size, 3);
	});

	it("supports two-word names for callers that append their own id", () => {
		const name = generateName({ words: 2, rng: sequenceRng([0, 0]) });

		assert.match(name, /^[a-z]+-[a-z]+$/);
		assert.equal(name.split("-").length, 2);
	});

	it("uses injected rng deterministically", () => {
		const first = generateName({ rng: sequenceRng([0, 0, 0]) });
		const second = generateName({ rng: sequenceRng([0, 0, 0]) });

		assert.equal(first, `${NAME_BANK[0]}-${NAME_BANK[1]}-${NAME_BANK[2]}`);
		assert.equal(second, first);
	});

	it("regenerates when a candidate is already taken", () => {
		const firstName = `${NAME_BANK[0]}-${NAME_BANK[1]}-${NAME_BANK[2]}`;
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
