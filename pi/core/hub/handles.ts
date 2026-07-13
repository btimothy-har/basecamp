import { createHash, randomUUID } from "node:crypto";
import { ADJ_NOUN, generateName } from "../naming/index.ts";

/**
 * A deterministic [0, 1) stream derived from an opaque hex seed, so name
 * selection over the shared word bank is reproducible for a given entropy.
 */
function seededRng(seed: string): () => number {
	let counter = 0;
	return () => {
		const digest = createHash("sha256").update(`${seed}:${counter}`).digest();
		counter += 1;
		return digest.readUIntBE(0, 6) / 2 ** 48;
	};
}

/** Compose an `adjective-noun-hex6` handle from a hex entropy string. */
function buildAgentHandleFromEntropy(entropy: string): string {
	const name = generateName({ pattern: ADJ_NOUN, rng: seededRng(entropy) });
	return `${name}-${entropy.slice(0, 6)}`;
}

export function buildAgentHandle(): string {
	return buildAgentHandleFromEntropy(randomUUID().replace(/-/g, ""));
}

export function buildDeterministicAgentHandle(seed: string): string {
	return buildAgentHandleFromEntropy(createHash("sha256").update(seed).digest("hex"));
}
