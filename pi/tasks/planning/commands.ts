/** /show-plan command — view or re-review the current plan. */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getActivePlanRef } from "../lifecycle/goal-cycle.ts";
import type { TasksRuntime } from "../lifecycle/index.ts";
import type { PlanAccess } from "./index.ts";
import { showPlanReadOnly, showReviewOverlay } from "./review/index.ts";

export function registerPlanCommands(pi: ExtensionAPI, runtime: TasksRuntime, plan: PlanAccess): void {
	pi.registerCommand("show-plan", {
		description: "View current plan draft or approved plan",
		handler: async (_args, ctx) => {
			const draft = plan.getDraft();

			if (draft) {
				if (ctx.hasUI) {
					await showReviewOverlay(draft, ctx);
					ctx.ui.notify("Review updated. Agent will see feedback on next turn.", "info");
				}
				return;
			}

			const planRef = getActivePlanRef(runtime);
			if (planRef) {
				if (ctx.hasUI) {
					await showPlanReadOnly(planRef, ctx);
				}
				return;
			}

			if (ctx.hasUI) {
				ctx.ui.notify("No plan yet — ask the agent to plan a piece of work to create one.", "info");
			}
		},
	});
}
