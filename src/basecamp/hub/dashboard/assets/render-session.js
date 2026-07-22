import { el } from "/assets/dom.js";
import { currentGoal, elapsedTime, relativeTime, titleCase } from "/assets/model.js";
import { renderGoalStages } from "/assets/render-goal-stages.js";
import { renderTopology } from "/assets/render-topology.js";
import { metricList } from "/assets/render-ui.js";

export function renderSessionPage(root, state) {
	return el(
		"article",
		{ className: "detail-page session-page" },
		renderSessionHero(root),
		renderGoalStages(root, state),
		renderTopology(root, state),
	);
}

function renderSessionHero(root) {
	const duration = elapsedTime(root.created_at, root.live ? null : root.last_seen_at);
	return el(
		"header",
		{ className: "detail-hero grid-paper" },
		el(
			"p",
			{ className: "breadcrumbs" },
			el("span", { text: root.repo }),
			el("span", { text: "/" }),
			el("span", { text: root.worktree_label }),
			el("span", { text: "·" }),
			el("span", { className: root.live ? "live-label" : "recent-label", text: root.live ? "● Live" : "● Recent" }),
		),
		el("span", { className: "handle-tag hero-handle", text: root.root_handle }),
		el("h1", { text: root.session_name }),
		el(
			"p",
			{ className: "lead-line" },
			el("strong", { text: "Current goal" }),
			el("span", { text: currentGoal(root) }),
		),
		metricList([
			["Kind", titleCase(root.kind)],
			["Mode", root.agent_mode],
			["Model", root.model],
			["Branch", root.branch],
			[root.live ? "Connected" : "Last seen", root.live ? duration : relativeTime(root.last_seen_at)],
		]),
	);
}
