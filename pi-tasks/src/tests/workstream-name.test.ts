import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { generateWorkstreamName } from "../workstreams/name.ts";

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

describe("generateWorkstreamName", () => {
	it("returns three distinct lowercase hyphen-joined words matching safe label rules", () => {
		const name = generateWorkstreamName({ rng: sequenceRng([0, 0, 0]) });
		const words = name.split("-");

		assert.match(name, /^[A-Za-z0-9][A-Za-z0-9._-]*$/);
		assert.match(name, /^[a-z]+-[a-z]+-[a-z]+$/);
		assert.equal(words.length, 3);
		assert.equal(new Set(words).size, 3);
	});

	it("uses injected rng deterministically", () => {
		const first = generateWorkstreamName({ rng: sequenceRng([0, 0, 0]) });
		const second = generateWorkstreamName({ rng: sequenceRng([0, 0, 0]) });

		assert.equal(first, "steady-calm-bright");
		assert.equal(second, first);
	});

	it("regenerates when a candidate is already taken", () => {
		const taken = new Set(["steady-calm-bright"]);
		const seen: string[] = [];
		const name = generateWorkstreamName({
			rng: sequenceRng([0, 0, 0, 0.4, 0.4, 0.4]),
			isTaken(candidate) {
				seen.push(candidate);
				return taken.has(candidate);
			},
		});

		assert.deepEqual(seen, ["steady-calm-bright", name]);
		assert.notEqual(name, "steady-calm-bright");
		assert.equal(taken.has(name), false);
	});

	it("throws when attempts are exhausted", () => {
		assert.throws(
			() =>
				generateWorkstreamName({
					rng: sequenceRng([0, 0, 0, 0, 0, 0]),
					isTaken: () => true,
					maxAttempts: 2,
				}),
			/Unable to generate an available workstream name after 2 attempts/,
		);
	});
});
