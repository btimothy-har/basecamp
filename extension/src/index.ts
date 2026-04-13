import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerLifecycle } from "./lifecycle";
import { registerGitProtect } from "./git-protect";
import { registerObserver } from "./observer";
import { registerMessaging } from "./messaging";
import { registerWorkers } from "./workers";
import { registerNudges } from "./nudges";

export default function (pi: ExtensionAPI) {
  registerLifecycle(pi);    // session init, env setup, project context injection
  registerGitProtect(pi);   // block destructive git/gh commands
  registerObserver(pi);     // observer ingest on compact/shutdown/dispatch
  registerMessaging(pi);    // inter-agent inbox consumption
  registerWorkers(pi);      // worker close-on-exit
  registerNudges(pi);       // skill suggestions on file edits
}
