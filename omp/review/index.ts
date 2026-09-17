import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerReviewCommand from "./command.ts";
import registerReviewTool from "./tool.ts";

export default function registerReview(pi: ExtensionAPI): void {
	registerReviewCommand(pi);
	registerReviewTool(pi);
}
