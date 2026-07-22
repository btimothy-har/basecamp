import { el } from "/assets/dom.js";
import {
	agentSummary,
	assignment,
	descendantContexts,
	elapsedTime,
	titleCase,
	visibleContexts,
} from "/assets/model.js";
import { emptyPanel, sectionHeading } from "/assets/render-ui.js";

export function renderTopology(root, state) {
	const contexts = visibleContexts(root, state.filters);
	const depth = contexts.reduce((max, context) => Math.max(max, context.depth + 1), 0);
	const heading = sectionHeading(
		"agent-topology-heading",
		"Agent topology",
		`${contexts.length}${root.agents_truncated ? "+" : ""} ${contexts.length === 1 ? "agent" : "agents"} · ${depth} ${depth === 1 ? "level" : "levels"}`,
	);
	if (root.agents.length === 0) {
		return el(
			"section",
			{ className: "content-section topology-section", attrs: { "aria-labelledby": "agent-topology-heading" } },
			heading,
			emptyPanel("No agents dispatched", "This session still has its goal stages, task plan, mode, and model above."),
		);
	}
	if (contexts.length === 0) {
		return el(
			"section",
			{ className: "content-section topology-section", attrs: { "aria-labelledby": "agent-topology-heading" } },
			heading,
			emptyPanel("No agents match", "The current agent status and type filters have no overlap in this session."),
		);
	}
	return el(
		"section",
		{ className: "content-section topology-section", attrs: { "aria-labelledby": "agent-topology-heading" } },
		heading,
		el(
			"div",
			{ className: "agent-table" },
			el(
				"div",
				{ className: "agent-table-head", attrs: { "aria-hidden": "true" } },
				el("span", { text: "Status / type" }),
				el("span", { text: "Current assignment" }),
				el("span", { text: "Model" }),
				el("span", { text: "Elapsed" }),
			),
			contexts.map((context) => agentRow(root, context)),
		),
		root.agents_truncated
			? el("p", { className: "bounded-note", text: "Topology is bounded to 100 agents for this session." })
			: null,
	);
}

export function agentRow(root, context, relativeDepth = context.depth) {
	const { agent } = context;
	const endedAt = ["completed", "failed"].includes(agent.status) ? agent.ended_at : null;
	return el(
		"button",
		{
			className: `agent-row${context.contextOnly ? " context-only" : ""}`,
			attrs: { type: "button" },
			data: { action: "selectAgent", rootHandle: root.root_handle, agentHandle: agent.agent_handle },
			style: { "--depth": Math.max(0, relativeDepth) },
		},
		el(
			"span",
			{ className: "agent-identity" },
			el(
				"span",
				{ className: "agent-status-line" },
				el("span", { className: `status-dot ${agent.status}`, attrs: { "aria-hidden": "true" } }),
				el("strong", { className: `status-text ${agent.status}`, text: titleCase(agent.status) }),
				el("span", { text: agent.agent_type }),
			),
			el("small", { text: agent.agent_handle }),
		),
		el(
			"span",
			{ className: "assignment-cell" },
			el("strong", { text: assignment(agent) }),
			el("small", { text: agentSummary(agent) }),
			el("small", {
				className: "lineage",
				text: context.contextOnly ? "ancestor retained for context" : lineageText(root, context),
			}),
		),
		el("span", { className: "model-cell", text: agent.model }),
		el("span", { className: "elapsed-cell", text: elapsedTime(agent.started_at, endedAt) }),
	);
}

function lineageText(root, context) {
	const parent = context.parent?.agent_handle ?? root.root_handle;
	const count = descendantContexts(root, context.agent.agent_handle).length;
	return `child of ${parent}${count ? ` · ${count} ${count === 1 ? "descendant" : "descendants"}` : ""}`;
}
