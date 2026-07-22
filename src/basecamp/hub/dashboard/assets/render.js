import { actionButton, append, el, option, replace } from "/assets/dom.js";
import {
	activityText,
	agentFiltersActive,
	agentSummary,
	assignment,
	clockTime,
	contextsForRoot,
	currentGoal,
	defaultStageIndex,
	descendantContexts,
	elapsedTime,
	findAgentContext,
	matchingContexts,
	progressPercent,
	relativeTime,
	selectedStage,
	stagesForRoot,
	titleCase,
	uniqueValues,
	visibleContexts,
	visibleRoots,
} from "/assets/model.js";

const nodes = {
	liveCount: document.querySelector("#live-count"),
	recentCount: document.querySelector("#recent-count"),
	agentCount: document.querySelector("#agent-count"),
	connectionChip: document.querySelector("#connection-chip"),
	connectionLabel: document.querySelector("#connection-label"),
	windowHours: document.querySelector("#window-hours"),
	repoFilter: document.querySelector("#repo-filter"),
	worktreeFilter: document.querySelector("#worktree-filter"),
	kindFilter: document.querySelector("#kind-filter"),
	liveFilter: document.querySelector("#live-filter"),
	statusFilter: document.querySelector("#status-filter"),
	typeFilter: document.querySelector("#type-filter"),
	offlineBanner: document.querySelector("#offline-banner"),
	visibleCount: document.querySelector("#visible-count"),
	sessionRail: document.querySelector("#session-rail"),
	workspace: document.querySelector("#workspace"),
};

export function renderDashboard(state) {
	const focus = focusedAction();
	const roots = visibleRoots(state.snapshot, state.filters);
	renderConnection(state);
	renderFilters(state);
	renderCounts(roots, state.filters);
	renderRail(state, roots);
	renderWorkspace(state, roots);
	restoreFocusedAction(focus);
	return roots;
}

function renderConnection(state) {
	nodes.connectionChip.className = `connection-chip ${state.connection}`;
	nodes.connectionLabel.textContent =
		state.connection === "connected"
			? "Hub online"
			: state.connection === "offline"
				? "Cached · hub offline"
				: "Connecting";
	nodes.offlineBanner.hidden = state.connection !== "offline" || !state.snapshot;
	if (!nodes.offlineBanner.hidden) {
		const age = relativeTime(state.snapshot.generated_at);
		nodes.offlineBanner.textContent = `Hub connection interrupted. Showing the last safe snapshot from ${age}.`;
	}
}

function renderFilters(state) {
	const roots = state.snapshot?.roots ?? [];
	const repoValues = uniqueValues(roots.map((root) => root.repo));
	const worktreeRoots = state.filters.repo === "all" ? roots : roots.filter((root) => root.repo === state.filters.repo);
	const worktreeValues = uniqueValues(worktreeRoots.map((root) => root.worktree_label));
	const contexts = roots.flatMap(contextsForRoot);
	setOptions(nodes.repoFilter, repoValues, "All repositories", state.filters.repo, (value) => value);
	setOptions(nodes.worktreeFilter, worktreeValues, "All worktrees", state.filters.worktree, (value) => value);
	setOptions(
		nodes.kindFilter,
		uniqueValues(roots.map((root) => root.kind)),
		"All kinds",
		state.filters.kind,
		titleCase,
	);
	setOptions(
		nodes.statusFilter,
		uniqueValues(contexts.map(({ agent }) => agent.status)),
		"Any status",
		state.filters.status,
		titleCase,
	);
	setOptions(
		nodes.typeFilter,
		uniqueValues(contexts.map(({ agent }) => agent.agent_type)),
		"Any agent type",
		state.filters.type,
		titleCase,
	);
	nodes.liveFilter.checked = state.filters.liveOnly;
	nodes.windowHours.textContent = `${state.snapshot?.window_hours ?? 72}h`;
}

function setOptions(select, values, allLabel, current, format) {
	const desired = [["all", allLabel], ...values.map((value) => [value, format(value)])];
	const unchanged =
		select.options.length === desired.length &&
		desired.every(([value, label], index) => {
			const existing = select.options[index];
			return existing.value === value && existing.textContent === label;
		});
	if (!unchanged)
		replace(
			select,
			desired.map(([value, label]) => option(value, label)),
		);
	select.value = values.includes(current) ? current : "all";
}

function renderCounts(roots, filters) {
	const agents = roots.flatMap((root) => matchingContexts(root, filters));
	nodes.liveCount.textContent = String(roots.filter((root) => root.live).length);
	nodes.recentCount.textContent = String(roots.filter((root) => !root.live).length);
	nodes.agentCount.textContent = String(agents.length);
	nodes.visibleCount.textContent = `${roots.length} visible`;
}

function renderRail(state, roots) {
	if (!state.snapshot && state.connection === "loading") {
		replace(nodes.sessionRail, railSkeleton());
		return;
	}
	if (!state.snapshot || roots.length === 0) {
		const text = !state.snapshot
			? "The hub is unavailable. Retry from the detail pane."
			: state.snapshot.roots.length
				? "No sessions match these filters."
				: "No recent sessions yet.";
		replace(nodes.sessionRail, el("div", { className: "rail-empty", text }));
		return;
	}

	const grouped = new Map();
	for (const root of roots) {
		const repos = grouped.get(root.repo) ?? new Map();
		const sessions = repos.get(root.worktree_label) ?? [];
		sessions.push(root);
		repos.set(root.worktree_label, sessions);
		grouped.set(root.repo, repos);
	}

	const groups = [];
	for (const [repo, worktrees] of grouped) {
		const repoSection = el("section", { className: "repo-group" }, el("h3", { className: "repo-heading", text: repo }));
		for (const [worktree, sessions] of worktrees) {
			append(
				repoSection,
				el(
					"div",
					{ className: "worktree-group" },
					el("h4", { className: "worktree-heading", text: worktree }),
					sessions.map((root) => sessionButton(root, state)),
				),
			);
		}
		groups.push(repoSection);
	}
	replace(nodes.sessionRail, groups);
}

function sessionButton(root, state) {
	const matching = matchingContexts(root, state.filters).map(({ agent }) => agent);
	const count = agentFiltersActive(state.filters) ? matching.length : root.agent_count;
	const countText =
		count === 0 ? "no child agents" : `${count}${root.agents_truncated ? "+" : ""} ${count === 1 ? "agent" : "agents"}`;
	const button = el(
		"button",
		{
			className: `session-button${root.root_handle === state.selectedRootHandle ? " selected" : ""}`,
			attrs: { type: "button", "aria-pressed": root.root_handle === state.selectedRootHandle },
			data: { action: "selectRoot", rootHandle: root.root_handle },
		},
		el("span", { className: `session-state-dot ${root.live ? "live" : "recent"}`, attrs: { "aria-hidden": "true" } }),
		el("span", { className: "session-title", text: root.session_name }),
		el("time", {
			className: "session-age",
			text: relativeTime(root.last_seen_at),
			attrs: { datetime: root.last_seen_at },
		}),
		el(
			"span",
			{ className: "session-meta" },
			kindBadge(root.kind),
			el("span", { className: "session-meta-text", text: `${root.agent_mode} · ${root.model} · ${countText}` }),
		),
		renderSignal(matching.length ? matching : root.agents),
	);
	return button;
}

function renderSignal(agents) {
	if (!agents.length) return el("span", { className: "signal-empty", text: "top-level session · no child agents" });
	return el(
		"span",
		{ className: "agent-signal", attrs: { "aria-hidden": "true" } },
		agents.slice(0, 7).map((agent) =>
			el("span", {
				className: `signal-segment ${agent.status}`,
				attrs: { title: `${agent.agent_type}: ${agent.status}` },
			}),
		),
	);
}

function renderWorkspace(state, roots) {
	if (!state.snapshot) {
		replace(nodes.workspace, state.connection === "loading" ? workspaceSkeleton() : unavailableState());
		return;
	}
	if (state.snapshot.roots.length === 0) {
		replace(
			nodes.workspace,
			emptyState(
				`No sessions in the ${state.snapshot.window_hours}-hour window`,
				"Start a Basecamp Pi session, then refresh.",
			),
		);
		return;
	}
	if (roots.length === 0) {
		replace(
			nodes.workspace,
			emptyState(
				"No sessions match",
				"The selected repository, worktree, session kind, visibility, and agent filters have no overlap.",
				"Reset filters",
				"resetFilters",
			),
		);
		return;
	}
	const root = roots.find((item) => item.root_handle === state.selectedRootHandle) ?? roots[0];
	const agentContext = state.selectedAgentHandle ? findAgentContext(root, state.selectedAgentHandle) : null;
	replace(nodes.workspace, agentContext ? renderAgentPage(root, agentContext, state) : renderSessionPage(root, state));
}

function renderSessionPage(root, state) {
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

function renderGoalStages(root, state) {
	const stages = stagesForRoot(root);
	if (!stages.length) {
		return contentSection("Goal stages", "No goal or task plan has been recorded for this session.");
	}
	const requestedIndex = state.selectedStageIndex ?? defaultStageIndex(root);
	const stage = selectedStage(root, requestedIndex);
	const stageTabs = el(
		"div",
		{ className: "stage-tabs", attrs: { role: "tablist", "aria-label": "Goal stages" } },
		stages.map((item, position) => stageButton(root, item, position, item.index === stage.index)),
	);
	const tasks = Array.isArray(stage.tasks) ? stage.tasks : [];
	const activeTask = tasks.find((task) => task.status === "active") ?? tasks.find((task) => task.status === "pending");
	const percent = progressPercent(stage.progress);
	return el(
		"section",
		{ className: "content-section goal-section", attrs: { "aria-labelledby": "goal-stages-heading" } },
		sectionHeading(
			"goal-stages-heading",
			"Goal stages",
			`${root.stage_count || stages.length} ${root.stage_count === 1 ? "stage" : "stages"}${root.stages_truncated ? " · latest shown" : ""}`,
		),
		stageTabs,
		el(
			"div",
			{
				className: "selected-goal",
				attrs: { role: "tabpanel", id: "selected-stage-panel", "aria-labelledby": stageTabId(root, stage) },
			},
			el("span", { className: "label", text: "Selected goal" }),
			el("p", { text: stage.goal ?? "No goal text recorded." }),
		),
		el(
			"div",
			{ className: "task-plan" },
			el(
				"aside",
				{ className: "progress-panel" },
				el("strong", { className: "progress-number", text: `${percent}%` }),
				el("span", { className: "progress-caption", text: "complete" }),
				el(
					"div",
					{
						className: "progress-track",
						attrs: { role: "progressbar", "aria-valuenow": percent, "aria-valuemin": 0, "aria-valuemax": 100 },
					},
					el("span", { style: { width: `${percent}%` } }),
				),
				el("span", { className: "label", text: "Current task" }),
				el("p", { text: activeTask?.label ?? "No active task" }),
			),
			el(
				"ol",
				{ className: "task-list" },
				tasks.length
					? tasks.map((task, position) => taskRow(task, position))
					: el("li", { className: "task-empty", text: "No tasks recorded for this stage." }),
			),
		),
		stage.tasks_truncated
			? el("p", { className: "bounded-note", text: "Task list is bounded to the first 20 visible tasks." })
			: null,
	);
}

function stageButton(root, stage, position, selected) {
	const complete = stage.progress?.total > 0 && stage.progress.completed >= stage.progress.total;
	const title = stageTitle(stage, position);
	return el(
		"button",
		{
			className: `stage-button${selected ? " selected" : ""}${complete ? " complete" : ""}`,
			attrs: {
				type: "button",
				role: "tab",
				id: stageTabId(root, stage),
				"aria-selected": selected,
				"aria-controls": "selected-stage-panel",
				tabindex: selected ? 0 : -1,
			},
			data: { action: "selectStage", rootHandle: root.root_handle, stageIndex: stage.index },
		},
		el("span", { className: "stage-number", text: complete ? "✓" : String(position + 1).padStart(2, "0") }),
		el(
			"span",
			{ className: "stage-copy" },
			el("strong", { text: title }),
			el("small", {
				text: stage.active ? "current" : stage.archived_at ? `archived ${relativeTime(stage.archived_at)}` : "previous",
			}),
		),
	);
}

function stageTabId(root, stage) {
	return `stage-tab-${root.root_handle}-${stage.index}`;
}

function stageTitle(stage, position) {
	const active = stage.tasks?.find((task) => task.status === "active")?.label;
	if (active) return active;
	const words = String(stage.goal ?? `Goal stage ${position + 1}`)
		.split(/\s+/)
		.filter(Boolean);
	return words.length > 7 ? `${words.slice(0, 7).join(" ")}…` : words.join(" ");
}

function taskRow(task, position) {
	return el(
		"li",
		{ className: `task-row ${task.status ?? "pending"}` },
		el("span", { className: "task-index", text: task.status === "completed" ? "✓" : position + 1 }),
		el(
			"span",
			{ className: "task-copy" },
			el("strong", { text: task.label ?? "Untitled task" }),
			task.description ? el("small", { text: task.description }) : null,
		),
		el("span", { className: "task-status", text: task.status ?? "pending" }),
	);
}

function renderTopology(root, state) {
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

function agentRow(root, context, relativeDepth = context.depth) {
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

function renderAgentPage(root, context, state) {
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

function renderRunDetail(root, context, state) {
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

function metricList(items, className = "metric-list") {
	return el(
		"dl",
		{ className },
		items.map(([term, value]) =>
			el("div", {}, el("dt", { text: term }), el("dd", { text: value === null || value === undefined ? "—" : value })),
		),
	);
}

function sectionHeading(id, title, kicker) {
	return el(
		"header",
		{ className: "section-heading" },
		el("h2", { attrs: { id }, text: title }),
		el("span", { text: kicker }),
	);
}

function contentSection(title, copy) {
	return el("section", { className: "content-section" }, el("h2", { text: title }), emptyPanel(title, copy));
}

function kindBadge(kind) {
	return el("span", { className: `kind-badge ${kind}`, text: titleCase(kind) });
}

function emptyPanel(title, copy) {
	return el("div", { className: "empty-panel" }, el("strong", { text: title }), el("p", { text: copy }));
}

function emptyState(title, copy, actionLabel = null, action = null) {
	return el(
		"section",
		{ className: "full-state" },
		el("span", { className: "state-mark", text: "B_" }),
		el("h1", { text: title }),
		el("p", { text: copy }),
		action ? actionButton(actionLabel, action, {}, "button") : null,
	);
}

function unavailableState() {
	return el(
		"section",
		{ className: "full-state unavailable" },
		el("span", { className: "state-mark", text: "B_" }),
		el("h1", { text: "Dashboard unavailable" }),
		el("p", {
			text: "The local hub could not provide a safe snapshot. Run basecamp agents again if authentication expired.",
		}),
		actionButton("Retry connection", "retrySnapshot", {}, "button"),
		el("code", { text: "basecamp agents" }),
	);
}

function railSkeleton() {
	return el(
		"div",
		{ className: "rail-skeleton", attrs: { "aria-label": "Loading sessions" } },
		...Array.from({ length: 5 }, (_, index) => el("span", { className: `loading-line${index % 2 ? " short" : ""}` })),
	);
}

function workspaceSkeleton() {
	return el(
		"div",
		{ className: "loading-state", attrs: { "aria-label": "Loading session detail" } },
		el("span", { className: "loading-line wide" }),
		el("span", { className: "loading-line" }),
		el("span", { className: "loading-block" }),
	);
}

function focusedAction() {
	const active = document.activeElement;
	if (!(active instanceof HTMLElement) || !active.dataset.action) return null;
	return {
		action: active.dataset.action,
		rootHandle: active.dataset.rootHandle,
		agentHandle: active.dataset.agentHandle,
		stageIndex: active.dataset.stageIndex,
	};
}

function restoreFocusedAction(focus) {
	if (!focus) return;
	requestAnimationFrame(() => {
		const target = [...document.querySelectorAll("[data-action]")].find(
			(element) =>
				element.dataset.action === focus.action &&
				element.dataset.rootHandle === focus.rootHandle &&
				element.dataset.agentHandle === focus.agentHandle &&
				element.dataset.stageIndex === focus.stageIndex,
		);
		target?.focus({ preventScroll: true });
	});
}
