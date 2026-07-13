import { NAME_BANK } from "./bank.ts";

export interface GenerateNameOptions {
	/** How many words to join. Defaults to 3 (readable slugs); 2 suits handles that append their own id. */
	words?: 2 | 3;
	/** Randomness source in [0, 1). Defaults to Math.random; pass a seeded rng for deterministic output. */
	rng?: () => number;
	/** Whether the chosen words must differ from one another. Defaults to true. */
	distinct?: boolean;
	/** Optional collision check; a truthy result rejects the candidate and retries. */
	isTaken?: (name: string) => boolean;
	/** How many candidates to try before giving up when isTaken keeps rejecting. Defaults to 50. */
	maxAttempts?: number;
}

function randomIndex(length: number, rng: () => number): number {
	const value = rng();
	if (!Number.isFinite(value) || value < 0 || value >= 1) {
		throw new Error("Name rng must return a number in the range [0, 1).");
	}
	return Math.floor(value * length);
}

function candidateName(wordCount: number, distinct: boolean, rng: () => number): string {
	const pool = [...NAME_BANK];
	const words: string[] = [];

	for (let i = 0; i < wordCount; i += 1) {
		const index = randomIndex(pool.length, rng);
		const word = distinct ? pool.splice(index, 1)[0] : pool[index];
		if (!word) {
			throw new Error("Unable to select a name word.");
		}
		words.push(word);
	}

	return words.join("-");
}

/**
 * Build a readable hyphen-joined name from the shared word bank — e.g.
 * `steady-calm-otter`. Callers own any prefix/suffix (a `copilot/` label, a
 * hex handle id, a session tag); this returns only the words.
 */
export function generateName(options: GenerateNameOptions = {}): string {
	const rng = options.rng ?? Math.random;
	const wordCount = options.words ?? 3;
	const distinct = options.distinct ?? true;
	const maxAttempts = options.maxAttempts ?? 50;

	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		const candidate = candidateName(wordCount, distinct, rng);
		if (!options.isTaken?.(candidate)) {
			return candidate;
		}
	}

	throw new Error(`Unable to generate an available name after ${maxAttempts} attempts.`);
}
