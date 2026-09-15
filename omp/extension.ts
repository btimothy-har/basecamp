import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerFileLengthReminder from "./engineering/file-length.ts";
import registerReview from "./review/index.ts";

export default function registerBasecamp(pi: ExtensionAPI): void {
	registerFileLengthReminder(pi);
	registerReview(pi);
}
