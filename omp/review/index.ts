import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerReviewInstructions from "./instructions.ts";
import registerReviewTool from "./tool.ts";

export default function registerReview(pi: ExtensionAPI): void {
	registerReviewInstructions(pi);
	registerReviewTool(pi);
}
