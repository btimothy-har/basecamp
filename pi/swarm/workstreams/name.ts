export interface GenerateWorkstreamNameOptions {
	isTaken?: (name: string) => boolean;
	maxAttempts?: number;
	rng?: () => number;
}

const WORKSTREAM_NAME_WORDS = [
	"steady",
	"calm",
	"bright",
	"quiet",
	"gentle",
	"brisk",
	"clear",
	"warm",
	"soft",
	"fresh",
	"kind",
	"smooth",
	"nimble",
	"brave",
	"mellow",
	"sunny",
	"crisp",
	"vivid",
	"light",
	"sturdy",
	"amber",
	"pebble",
	"otter",
	"cedar",
	"meadow",
	"river",
	"harbor",
	"lantern",
	"willow",
	"fox",
	"sparrow",
	"turtle",
	"stone",
	"cloud",
	"breeze",
	"orchard",
	"maple",
	"coral",
	"heron",
	"acorn",
	"fern",
	"valley",
	"summit",
	"shell",
	"comet",
	"lark",
	"moss",
	"pine",
	"brook",
	"dune",
] as const;

function randomIndex(length: number, rng: () => number): number {
	const value = rng();
	if (!Number.isFinite(value) || value < 0 || value >= 1) {
		throw new Error("Workstream name rng must return a number in the range [0, 1).");
	}
	return Math.floor(value * length);
}

function candidateName(rng: () => number): string {
	const available = [...WORKSTREAM_NAME_WORDS];
	const words: string[] = [];

	for (let i = 0; i < 3; i += 1) {
		const [word] = available.splice(randomIndex(available.length, rng), 1);
		if (!word) {
			throw new Error("Unable to select a workstream name word.");
		}
		words.push(word);
	}

	return words.join("-");
}

export function generateWorkstreamName(options: GenerateWorkstreamNameOptions = {}): string {
	const rng = options.rng ?? Math.random;
	const maxAttempts = options.maxAttempts ?? 50;

	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		const candidate = candidateName(rng);
		if (!options.isTaken?.(candidate)) {
			return candidate;
		}
	}

	throw new Error(`Unable to generate an available workstream name after ${maxAttempts} attempts.`);
}
