import { actionButton, el } from "/assets/dom.js";
import { activityText, agentSummary, assignment, clockTime, descendantContexts, titleCase } from "/assets/model.js";
import { metricList, sectionHeading } from "/assets/render-ui.js";

export function renderRunDetail(root, context, state) {
	const { agent } = context;
	const messageKey = `${root.root_handle}/${agent.agent_handle}`;
	const messageState = state.messages.get(messageKey);
	return el(
		"section",
		{ className: "content-section run-section", attrs: { "aria-labelledby": "run-detail-heading" } },
		sectionHeading("run-detail-heading", "Run detail", "bounded projection"),
		el(
			"div",
			{ className: "run-card" },
			el(
				"header",
				{ className: "run-card-heading" },
				el(
					"div",
					{},
					el("strong", { text: agent.agent_type }),
					el("span", { className: `status-dot ${agent.status}`, attrs: { "aria-hidden": "true" } }),
					el("strong", { className: `status-text ${agent.status}`, text: titleCase(agent.status) }),
				),
				metricList(
					[
						["Events", agent.recent_activity.length],
						["Messages", messageState?.messages?.length ?? "—"],
						[
							"Children",
							descendantContexts(root, agent.agent_handle).filter((item) => item.depth === context.depth + 1).length,
						],
					],
					"run-counts",
				),
			),
			runPanel("Current assignment", assignmentPanel(agent)),
			runPanel("Recent activity", activityPanel(agent)),
			runPanel("Skills", skillsPanel(agent)),
			runPanel("Message previews", messagesPanel(root, agent, messageState)),
			runPanel(resultHeading(agent.status), resultPanel(agent)),
		),
	);
}

function assignmentPanel(agent) {
	return el(
		"div",
		{ className: "run-copy" },
		el("strong", { text: assignment(agent) }),
		el("p", { text: agent.task?.current_task?.description ?? agentSummary(agent) }),
	);
}

function activityPanel(agent) {
	if (!agent.recent_activity.length) return el("p", { className: "muted", text: "No activity recorded yet." });
	return el(
		"ol",
		{ className: "activity-list" },
		agent.recent_activity.map((activity) =>
			el(
				"li",
				{},
				el("time", { text: clockTime(activity.timestamp), attrs: { datetime: activity.timestamp } }),
				el("span", { className: "activity-kind", text: activity.category ?? activity.kind }),
				el("span", { text: activityText(activity) }),
			),
		),
	);
}

function skillsPanel(agent) {
	if (!agent.skills.length) return el("p", { className: "muted", text: "No skill invocations recorded for this run." });
	return el(
		"div",
		{ className: "skill-list" },
		agent.skills.map((skill) =>
			el("span", {
				className: "skill-chip",
				text: `${skill.name ?? "skill"}${skill.count > 1 ? ` ×${skill.count}` : ""}`,
			}),
		),
	);
}

function messagesPanel(root, agent, messageState) {
	if (!messageState || messageState.status === "loading") {
		return el("p", { className: "muted", text: "Loading bounded assistant messages…" });
	}
	if (messageState.status === "error") {
		return el(
			"div",
			{ className: "inline-error" },
			el("p", { text: "Message previews are temporarily unavailable." }),
			actionButton(
				"Retry messages",
				"retryMessages",
				{ rootHandle: root.root_handle, agentHandle: agent.agent_handle },
				"text-button",
			),
		);
	}
	if (!messageState.messages.length)
		return el("p", { className: "muted", text: "No bounded message previews for this run." });
	return el(
		"ol",
		{ className: "message-list" },
		messageState.messages.map((message) =>
			el(
				"li",
				{},
				el(
					"header",
					{},
					el("strong", { text: message.label ?? "assistant" }),
					el("time", { text: clockTime(message.timestamp), attrs: { datetime: message.timestamp } }),
				),
				el("p", { text: message.text }),
				message.truncated ? el("small", { text: "Message truncated by the bounded projection." }) : null,
			),
		),
	);
}

function resultHeading(status) {
	if (status === "failed") return "Failure preview";
	if (status === "completed") return "Result preview";
	return "Current report";
}

function resultPanel(agent) {
	const text = agent.status === "failed" ? agent.error_preview : agent.result_preview;
	return el(
		"div",
		{ className: `result-panel ${agent.status}` },
		el("p", {
			text: text ?? (agent.status === "running" ? "Run is still active." : "No result preview is available."),
		}),
		agent.exit_code !== null && agent.exit_code !== undefined
			? el("small", { text: `Exit code ${agent.exit_code}` })
			: null,
	);
}

function runPanel(title, content) {
	return el("section", { className: "run-panel" }, el("h3", { text: title }), content);
}
