import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerReviewTool from "./tool.ts";

export default function registerReview(pi: ExtensionAPI): void {
	registerReviewTool(pi);
}
