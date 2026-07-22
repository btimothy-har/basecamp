import { el } from "/assets/dom.js";
import { defaultStageIndex, progressPercent, relativeTime, selectedStage, stagesForRoot } from "/assets/model.js";
import { contentSection, sectionHeading } from "/assets/render-ui.js";

export function renderGoalStages(root, state) {
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
