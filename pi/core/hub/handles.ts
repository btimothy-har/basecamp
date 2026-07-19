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

/**
 * Derive a handle deterministically from a seed (a node id): same seed → same
 * handle, so a top-level session keeps a stable, addressable identity across
 * reload/resume (see identity.ts), and peers cache that handle to reach it.
 *
 * The mapping is therefore a contract, not an implementation detail — it holds
 * only for a fixed algorithm and word bank. Changing seededRng, the entropy
 * slicing, or the shared naming bank re-derives a different handle for every
 * existing seed. A session live across such a change reconnects under the new
 * handle (the daemon overwrites the stored handle with the freshly-derived one
 * on reconnect), and peers addressing the old handle get a silent "unknown"
 * ack, not an error. Change deliberately.
 */
export function buildDeterministicAgentHandle(seed: string): string {
	return buildAgentHandleFromEntropy(createHash("sha256").update(seed).digest("hex"));
}
