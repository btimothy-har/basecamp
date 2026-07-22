import { actionButton, el } from "/assets/dom.js";
import { agentSummary, assignment, clockTime, descendantContexts, elapsedTime, titleCase } from "/assets/model.js";
import { renderRunDetail } from "/assets/render-run-detail.js";
import { agentRow } from "/assets/render-topology.js";
import { emptyPanel, metricList, sectionHeading } from "/assets/render-ui.js";

export function renderAgentPage(root, context, state) {
	const { agent } = context;
	const descendants = descendantContexts(root, agent.agent_handle);
	return el(
		"article",
		{ className: "detail-page agent-page" },
		renderAgentHero(root, context, descendants),
		renderDescendants(root, context, descendants),
		renderRunDetail(root, context, state),
	);
}

function renderAgentHero(root, context, descendants) {
	const { agent } = context;
	return el(
		"header",
		{ className: "detail-hero agent-hero grid-paper" },
		actionButton("← Session overview", "selectRoot", { rootHandle: root.root_handle }, "back-button"),
		el(
			"nav",
			{ className: "agent-breadcrumbs", attrs: { "aria-label": "Agent ancestry" } },
			breadcrumbButton(root.session_name, "selectRoot", { rootHandle: root.root_handle }),
			context.ancestors.flatMap((ancestor) => [
				el("span", { text: "/" }),
				breadcrumbButton(`${ancestor.agent_type} ${ancestor.agent_handle}`, "selectAgent", {
					rootHandle: root.root_handle,
					agentHandle: ancestor.agent_handle,
				}),
			]),
			el("span", { text: "/" }),
			el("strong", { text: `${agent.agent_type} ${agent.agent_handle}` }),
		),
		el("span", { className: "handle-tag hero-handle", text: agent.agent_handle }),
		el(
			"p",
			{ className: "agent-kicker" },
			el("span", { text: agent.agent_type }),
			el("span", { className: `status-dot ${agent.status}`, attrs: { "aria-hidden": "true" } }),
			el("strong", { className: `status-text ${agent.status}`, text: titleCase(agent.status) }),
		),
		el("h1", { text: assignment(agent) }),
		el("p", { className: "lead-line" }, el("strong", { text: "Context" }), el("span", { text: agentSummary(agent) })),
		metricList([
			["Parent", context.parent?.agent_handle ?? root.root_handle],
			["Depth", context.depth + 1],
			["Model", agent.model],
			["Started", clockTime(agent.started_at)],
			[
				"Runtime",
				elapsedTime(agent.started_at, ["completed", "failed"].includes(agent.status) ? agent.ended_at : null),
			],
			["Descendants", descendants.length],
		]),
	);
}

function breadcrumbButton(label, action, data) {
	return actionButton(label, action, data, "breadcrumb-button");
}

function renderDescendants(root, context, descendants) {
	const heading = sectionHeading(
		"descendants-heading",
		"Dispatched agents",
		descendants.length
			? `${descendants.length} ${descendants.length === 1 ? "descendant" : "descendants"}`
			: "leaf agent",
	);
	if (!descendants.length) {
		return el(
			"section",
			{ className: "content-section descendants-section", attrs: { "aria-labelledby": "descendants-heading" } },
			heading,
			emptyPanel("No descendants", "This agent is a leaf in the current bounded topology."),
		);
	}
	return el(
		"section",
		{ className: "content-section descendants-section", attrs: { "aria-labelledby": "descendants-heading" } },
		heading,
		el(
			"div",
			{ className: "agent-table compact" },
			descendants.map((descendant) => agentRow(root, descendant, Math.max(0, descendant.depth - context.depth - 1))),
		),
	);
}
