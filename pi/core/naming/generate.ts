import { ADJECTIVES, NOUNS } from "./bank.ts";

export type PartOfSpeech = "adjective" | "noun";

const POOLS: Record<PartOfSpeech, readonly string[]> = {
	adjective: ADJECTIVES,
	noun: NOUNS,
};

/** Agent-handle grammar: `adjective-noun` (callers append a unique id, e.g. a hex suffix). */
export const ADJ_NOUN: readonly PartOfSpeech[] = ["adjective", "noun"];

/** Readable-slug grammar: `adjective-adjective-noun`. */
export const ADJ_ADJ_NOUN: readonly PartOfSpeech[] = ["adjective", "adjective", "noun"];

export interface GenerateNameOptions {
	/** Part of speech per position. Defaults to adjective-adjective-noun. */
	pattern?: readonly PartOfSpeech[];
	/** Randomness source in [0, 1). Defaults to Math.random; pass a seeded rng for deterministic output. */
	rng?: () => number;
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

function candidateName(pattern: readonly PartOfSpeech[], rng: () => number): string {
	// One mutable copy per part of speech, so repeated slots (e.g. two adjectives)
	// never draw the same word; different parts draw from disjoint lists already.
	const pools = new Map<PartOfSpeech, string[]>();
	const words: string[] = [];

	for (const pos of pattern) {
		let pool = pools.get(pos);
		if (!pool) {
			pool = [...POOLS[pos]];
			pools.set(pos, pool);
		}
		const [word] = pool.splice(randomIndex(pool.length, rng), 1);
		if (!word) {
			throw new Error(`Not enough ${pos} words to build the requested name.`);
		}
		words.push(word);
	}

	return words.join("-");
}

/**
 * Build a readable hyphen-joined name from the shared word bank following a
 * part-of-speech pattern — e.g. `steady-calm-otter` for adjective-adjective-noun.
 * Callers own any prefix/suffix (a `copilot/` label, a hex handle id, a session
 * tag); this returns only the words.
 */
export function generateName(options: GenerateNameOptions = {}): string {
	const rng = options.rng ?? Math.random;
	const pattern = options.pattern ?? ADJ_ADJ_NOUN;
	const maxAttempts = options.maxAttempts ?? 50;

	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		const candidate = candidateName(pattern, rng);
		if (!options.isTaken?.(candidate)) {
			return candidate;
		}
	}

	throw new Error(`Unable to generate an available name after ${maxAttempts} attempts.`);
}
