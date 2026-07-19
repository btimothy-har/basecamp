import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerReviewCommand } from "./command.ts";

/**
 * The `/code-review` feature domain — an independent, third-party multi-agent
 * review of the current branch, built on the swarm primitive (`#core/swarm`).
 * The primary agent triggers it and receives the findings as the reviewee; it
 * never authors or synthesizes the review.
 */
export default function registerCodeReview(pi: ExtensionAPI): void {
	registerReviewCommand(pi);
}
