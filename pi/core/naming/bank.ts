import { ADJECTIVES } from "./adjectives.ts";
import { NOUNS } from "./nouns.ts";

export { ADJECTIVES, NOUNS };

/** Every word, flat — for callers/tests that want the whole bank in one list. */
export const NAME_BANK: readonly string[] = [...ADJECTIVES, ...NOUNS];
