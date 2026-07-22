import { option, replace } from "/assets/dom.js";
import {
	contextsForRoot,
	findAgentContext,
	matchingContexts,
	relativeTime,
	titleCase,
	uniqueValues,
	visibleRoots,
} from "/assets/model.js";
import { renderAgentPage } from "/assets/render-agent.js";
import { renderRail } from "/assets/render-rail.js";
import { renderSessionPage } from "/assets/render-session.js";
import { emptyState, unavailableState, workspaceSkeleton } from "/assets/render-ui.js";

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
	renderRail(state, roots, nodes.sessionRail);
	renderWorkspace(state, roots);
	restoreFocusedAction(focus);
	return roots;
}

function renderConnection(state) {
	nodes.connectionChip.className = `connection-chip ${state.connection}`;
	nodes.connectionLabel.textContent =
		state.connection === "connected"
			? "Hub online"
			: state.connection === "busy"
				? "Cached · refresh busy"
				: state.connection === "offline"
					? "Cached · hub offline"
					: "Connecting";
	const showingCached = ["busy", "offline"].includes(state.connection) && state.snapshot;
	nodes.offlineBanner.hidden = !showingCached;
	if (!nodes.offlineBanner.hidden) {
		const age = relativeTime(state.snapshot.generated_at);
		nodes.offlineBanner.textContent =
			state.connection === "busy"
				? `Another snapshot refresh is still running. Showing cached data from ${age}.`
				: `Hub connection interrupted. Showing the last safe snapshot from ${age}.`;
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
	nodes.windowHours.textContent = `${state.snapshot?.window_hours ?? 24}h`;
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
