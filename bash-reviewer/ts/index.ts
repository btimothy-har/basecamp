import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBashReviewer } from "./src/reviewer/index.ts";

export default function (pi: ExtensionAPI) {
	registerBashReviewer(pi);
}
