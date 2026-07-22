import {
	contextsForRoot,
	DEFAULT_RECENT_ROOT_LIMIT,
	defaultStageIndex,
	EMPTY_FILTERS,
	findAgentContext,
	nextRecentRootLimit,
	normalizeSnapshot,
	parseRoute,
	routeFor,
	snapshotFailureState,
	uniqueValues,
	visibleRoots,
} from "/assets/model.js";
import { renderDashboard } from "/assets/render.js";

const POLL_INTERVAL_MS = 3000;
const state = {
	snapshot: null,
	connection: "loading",
	selectedRootHandle: null,
	selectedAgentHandle: null,
	selectedStageIndex: null,
	selectedStageRootHandle: null,
	filters: { ...EMPTY_FILTERS },
	recentRootLimit: DEFAULT_RECENT_ROOT_LIMIT,
	loadingMoreRoots: false,
	messages: new Map(),
};

const controls = {
	repo: document.querySelector("#repo-filter"),
	worktree: document.querySelector("#worktree-filter"),
	kind: document.querySelector("#kind-filter"),
	liveOnly: document.querySelector("#live-filter"),
	status: document.querySelector("#status-filter"),
	type: document.querySelector("#type-filter"),
	reset: document.querySelector("#reset-filters"),
	rail: document.querySelector("#session-rail"),
	workspace: document.querySelector("#workspace"),
	announcer: document.querySelector("#announcer"),
};

let pollTimer = null;
let refreshGeneration = 0;
let lastAnnouncedConnection = null;
const initialRoute = parseRoute(window.location.hash);
if (initialRoute) {
	state.selectedRootHandle = initialRoute.rootHandle;
	state.selectedAgentHandle = initialRoute.agentHandle;
}

function render() {
	if (state.snapshot) {
		reconcileFilters();
		reconcileSelection();
		syncRoute(true);
	}
	renderDashboard(state);
	if (lastAnnouncedConnection !== state.connection) {
		lastAnnouncedConnection = state.connection;
		announce(
			state.connection === "connected"
				? "Dashboard connected"
				: state.connection === "busy"
					? "Snapshot refresh busy. Cached data remains visible."
					: state.connection === "offline"
						? "Dashboard offline. Cached data remains visible."
						: "Connecting to dashboard",
		);
	}
}

function reconcileFilters() {
	if (!state.snapshot) return;
	const roots = state.snapshot.roots;
	const repoValues = uniqueValues(roots.map((root) => root.repo));
	if (state.filters.repo !== "all" && !repoValues.includes(state.filters.repo)) state.filters.repo = "all";
	const worktreeValues = uniqueValues(
		roots
			.filter((root) => state.filters.repo === "all" || root.repo === state.filters.repo)
			.map((root) => root.worktree_label),
	);
	if (state.filters.worktree !== "all" && !worktreeValues.includes(state.filters.worktree))
		state.filters.worktree = "all";
	const kindValues = uniqueValues(roots.map((root) => root.kind));
	if (state.filters.kind !== "all" && !kindValues.includes(state.filters.kind)) state.filters.kind = "all";
	const contexts = roots.flatMap(contextsForRoot);
	const statuses = uniqueValues(contexts.map(({ agent }) => agent.status));
	const types = uniqueValues(contexts.map(({ agent }) => agent.agent_type));
	if (state.filters.status !== "all" && !statuses.includes(state.filters.status)) state.filters.status = "all";
	if (state.filters.type !== "all" && !types.includes(state.filters.type)) state.filters.type = "all";
}

function reconcileSelection() {
	const roots = visibleRoots(state.snapshot, state.filters);
	let root = roots.find((item) => item.root_handle === state.selectedRootHandle) ?? null;
	if (!root) {
		root = roots[0] ?? null;
		state.selectedRootHandle = root?.root_handle ?? null;
		state.selectedAgentHandle = null;
	}
	if (root && state.selectedAgentHandle && !findAgentContext(root, state.selectedAgentHandle)) {
		state.selectedAgentHandle = null;
	}
	if (!root) {
		state.selectedStageIndex = null;
		state.selectedStageRootHandle = null;
		return;
	}
	if (state.selectedStageRootHandle !== root.root_handle) {
		state.selectedStageRootHandle = root.root_handle;
		state.selectedStageIndex = defaultStageIndex(root);
	}
	const stageExists = root.stages.some((stage) => stage.index === state.selectedStageIndex);
	if (root.stages.length && !stageExists) state.selectedStageIndex = defaultStageIndex(root);
}

async function refreshSnapshot() {
	clearTimeout(pollTimer);
	if (document.visibilityState === "hidden") return;
	const generation = ++refreshGeneration;
	let responseStatus = null;
	if (!state.snapshot) {
		state.connection = "loading";
		render();
	}
	try {
		const response = await fetch(snapshotPath(), {
			headers: { Accept: "application/json" },
			credentials: "same-origin",
			cache: "no-store",
		});
		responseStatus = response.status;
		if (!response.ok) throw new Error(`snapshot status ${response.status}`);
		const snapshot = normalizeSnapshot(await response.json());
		if (generation !== refreshGeneration) return;
		const loadedMore = state.loadingMoreRoots;
		state.snapshot = snapshot;
		state.recentRootLimit = snapshot.recent_root_limit;
		state.loadingMoreRoots = false;
		pruneMessageCache(snapshot);
		state.connection = "connected";
		render();
		if (loadedMore) announce(`Showing up to ${snapshot.recent_root_limit} recent sessions.`);
		loadSelectedMessages(true);
	} catch {
		if (generation !== refreshGeneration) return;
		const loadingMore = state.loadingMoreRoots;
		state.loadingMoreRoots = false;
		state.connection = snapshotFailureState(responseStatus, Boolean(state.snapshot));
		render();
		if (loadingMore) announce("More sessions will load on the next refresh.");
	} finally {
		if (generation === refreshGeneration) schedulePoll();
	}
}

function snapshotPath() {
	const params = new URLSearchParams({ recent_root_limit: String(state.recentRootLimit) });
	if (state.selectedRootHandle) params.set("selected_root_handle", state.selectedRootHandle);
	return `/api/snapshot?${params}`;
}

function loadMoreRoots() {
	if (!state.snapshot || state.loadingMoreRoots || state.recentRootLimit > state.snapshot.recent_root_limit) return;
	const nextLimit = nextRecentRootLimit(state.recentRootLimit, state.snapshot.recent_root_limit_max);
	if (nextLimit === state.recentRootLimit) return;
	state.recentRootLimit = nextLimit;
	state.loadingMoreRoots = true;
	renderDashboard(state);
	refreshSnapshot();
}

function schedulePoll() {
	clearTimeout(pollTimer);
	if (document.visibilityState !== "hidden") pollTimer = setTimeout(refreshSnapshot, POLL_INTERVAL_MS);
}

function selectRoot(rootHandle, { push = true } = {}) {
	state.selectedRootHandle = rootHandle;
	state.selectedAgentHandle = null;
	state.selectedStageRootHandle = null;
	reconcileSelection();
	syncRoute(!push);
	renderDashboard(state);
	focusWorkspace();
}

function selectAgent(rootHandle, agentHandle, { push = true } = {}) {
	state.selectedRootHandle = rootHandle;
	state.selectedAgentHandle = agentHandle;
	reconcileSelection();
	syncRoute(!push);
	renderDashboard(state);
	loadMessages(rootHandle, agentHandle, { force: true });
	focusWorkspace();
}

function syncRoute(replace) {
	if (!state.selectedRootHandle) return;
	const route = routeFor(state.selectedRootHandle, state.selectedAgentHandle);
	if (window.location.hash === route) return;
	if (replace) history.replaceState(null, "", route);
	else history.pushState(null, "", route);
}

function applyLocationRoute() {
	if (!state.snapshot) return;
	const route = parseRoute(window.location.hash);
	if (!route) {
		reconcileSelection();
		syncRoute(true);
		renderDashboard(state);
		return;
	}
	const root = state.snapshot.roots.find((item) => item.root_handle === route.rootHandle);
	if (!root) {
		reconcileSelection();
		syncRoute(true);
		renderDashboard(state);
		return;
	}
	if (!visibleRoots(state.snapshot, state.filters).some((item) => item.root_handle === route.rootHandle)) {
		state.filters = { ...EMPTY_FILTERS };
	}
	state.selectedRootHandle = route.rootHandle;
	state.selectedAgentHandle = route.agentHandle && findAgentContext(root, route.agentHandle) ? route.agentHandle : null;
	state.selectedStageRootHandle = null;
	reconcileSelection();
	syncRoute(true);
	renderDashboard(state);
	loadSelectedMessages();
	focusWorkspace();
}

function focusWorkspace() {
	controls.workspace.scrollTop = 0;
	if (window.matchMedia("(max-width: 820px)").matches) controls.workspace.scrollIntoView({ block: "start" });
	controls.workspace.focus({ preventScroll: true });
}

async function loadMessages(rootHandle, agentHandle, { force = false } = {}) {
	const key = `${rootHandle}/${agentHandle}`;
	const existing = state.messages.get(key);
	if (["loading", "refreshing"].includes(existing?.status) || (existing?.status === "ready" && !force)) return;
	state.messages.set(
		key,
		existing?.status === "ready"
			? { status: "refreshing", messages: existing.messages }
			: { status: "loading", messages: [] },
	);
	if (existing?.status !== "ready") renderDashboard(state);
	try {
		const query = new URLSearchParams({ root_handle: rootHandle, agent_handle: agentHandle });
		const response = await fetch(`/api/messages?${query}`, {
			headers: { Accept: "application/json" },
			credentials: "same-origin",
			cache: "no-store",
		});
		if (!response.ok) throw new Error(`message status ${response.status}`);
		const payload = await response.json();
		const messages = Array.isArray(payload.messages)
			? payload.messages.filter((message) => message && typeof message.text === "string")
			: [];
		state.messages.set(key, { status: "ready", messages });
	} catch {
		state.messages.set(key, existing?.status === "ready" ? existing : { status: "error", messages: [] });
	}
	renderDashboard(state);
}

function loadSelectedMessages(force = false) {
	if (!state.selectedRootHandle || !state.selectedAgentHandle || !state.snapshot) return;
	const root = state.snapshot.roots.find((item) => item.root_handle === state.selectedRootHandle);
	const agent = root ? findAgentContext(root, state.selectedAgentHandle)?.agent : null;
	if (!agent) return;
	const refreshLiveMessages = force && ["pending", "running"].includes(agent.status);
	loadMessages(state.selectedRootHandle, state.selectedAgentHandle, { force: refreshLiveMessages });
}

function pruneMessageCache(snapshot) {
	const activeKeys = new Set(
		snapshot.roots.flatMap((root) => root.agents.map((agent) => `${root.root_handle}/${agent.agent_handle}`)),
	);
	for (const key of state.messages.keys()) {
		if (!activeKeys.has(key)) state.messages.delete(key);
	}
}

function updateFilter(name, value) {
	state.filters[name] = value;
	if (name === "repo") {
		const allowed = state.snapshot?.roots
			.filter((root) => value === "all" || root.repo === value)
			.map((root) => root.worktree_label);
		if (state.filters.worktree !== "all" && !allowed?.includes(state.filters.worktree)) state.filters.worktree = "all";
	}
	reconcileSelection();
	syncRoute(true);
	renderDashboard(state);
}

function resetFilters() {
	state.filters = { ...EMPTY_FILTERS };
	reconcileSelection();
	syncRoute(true);
	renderDashboard(state);
}

function handleAction(button) {
	const { action, rootHandle, agentHandle, stageIndex } = button.dataset;
	if (action === "selectRoot" && rootHandle) selectRoot(rootHandle);
	if (action === "selectAgent" && rootHandle && agentHandle) selectAgent(rootHandle, agentHandle);
	if (action === "selectStage" && rootHandle) {
		state.selectedRootHandle = rootHandle;
		state.selectedStageRootHandle = rootHandle;
		state.selectedStageIndex = Number(stageIndex);
		renderDashboard(state);
	}
	if (action === "resetFilters") resetFilters();
	if (action === "loadMoreRoots") loadMoreRoots();
	if (action === "retrySnapshot") refreshSnapshot();
	if (action === "retryMessages" && rootHandle && agentHandle) loadMessages(rootHandle, agentHandle, { force: true });
}

function announce(message) {
	controls.announcer.textContent = "";
	requestAnimationFrame(() => {
		controls.announcer.textContent = message;
	});
}

for (const [name, control] of Object.entries({
	repo: controls.repo,
	worktree: controls.worktree,
	kind: controls.kind,
	status: controls.status,
	type: controls.type,
})) {
	control.addEventListener("change", () => updateFilter(name, control.value));
}
controls.liveOnly.addEventListener("change", () => updateFilter("liveOnly", controls.liveOnly.checked));
controls.reset.addEventListener("click", resetFilters);

document.addEventListener("click", (event) => {
	const button = event.target.closest("button[data-action]");
	if (button) handleAction(button);
});

controls.rail.addEventListener("keydown", (event) => {
	if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
	const buttons = [...controls.rail.querySelectorAll(".session-button")];
	const current = buttons.indexOf(document.activeElement);
	if (current < 0 || !buttons.length) return;
	event.preventDefault();
	const next =
		event.key === "Home"
			? 0
			: event.key === "End"
				? buttons.length - 1
				: (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
	buttons[next].focus();
});

document.addEventListener("keydown", (event) => {
	const button = event.target.closest(".stage-button");
	if (!button || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
	const buttons = [...button.parentElement.querySelectorAll(".stage-button")];
	const current = buttons.indexOf(button);
	event.preventDefault();
	const next =
		event.key === "Home"
			? 0
			: event.key === "End"
				? buttons.length - 1
				: (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
	buttons[next].focus();
	buttons[next].click();
});

document.addEventListener("visibilitychange", () => {
	if (document.visibilityState === "hidden") clearTimeout(pollTimer);
	else refreshSnapshot();
});
window.addEventListener("hashchange", applyLocationRoute);
window.addEventListener("popstate", applyLocationRoute);

render();
refreshSnapshot();
