import { createHash, randomUUID } from "node:crypto";

const HANDLE_ADJECTIVES = [
	"amber",
	"brisk",
	"calm",
	"clear",
	"ember",
	"mossy",
	"quiet",
	"silver",
	"steady",
	"swift",
] as const;
const HANDLE_NOUNS = ["badger", "falcon", "fox", "heron", "lynx", "otter", "panda", "raven", "tiger", "wren"] as const;

function buildAgentHandleFromEntropy(entropy: string): string {
	const adjective = HANDLE_ADJECTIVES[Number.parseInt(entropy.slice(0, 2), 16) % HANDLE_ADJECTIVES.length];
	const noun = HANDLE_NOUNS[Number.parseInt(entropy.slice(2, 4), 16) % HANDLE_NOUNS.length];
	return `${adjective}-${noun}-${entropy.slice(4, 10)}`;
}

export function buildAgentHandle(): string {
	return buildAgentHandleFromEntropy(randomUUID().replace(/-/g, ""));
}

export function buildDeterministicAgentHandle(seed: string): string {
	const entropy = createHash("sha256").update(seed).digest("hex");
	return buildAgentHandleFromEntropy(entropy);
}
