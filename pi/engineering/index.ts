import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerFileLengthReminder } from "./file-length.ts";

export default function (pi: ExtensionAPI): void {
	registerFileLengthReminder(pi);
}
