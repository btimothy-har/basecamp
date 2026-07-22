import { actionButton, el } from "/assets/dom.js";
import { titleCase } from "/assets/model.js";

export function metricList(items, className = "metric-list") {
	return el(
		"dl",
		{ className },
		items.map(([term, value]) =>
			el("div", {}, el("dt", { text: term }), el("dd", { text: value === null || value === undefined ? "—" : value })),
		),
	);
}

export function sectionHeading(id, title, kicker) {
	return el(
		"header",
		{ className: "section-heading" },
		el("h2", { attrs: { id }, text: title }),
		el("span", { text: kicker }),
	);
}

export function contentSection(title, copy) {
	return el("section", { className: "content-section" }, el("h2", { text: title }), emptyPanel(title, copy));
}

export function kindBadge(kind) {
	return el("span", { className: `kind-badge ${kind}`, text: titleCase(kind) });
}

export function emptyPanel(title, copy) {
	return el("div", { className: "empty-panel" }, el("strong", { text: title }), el("p", { text: copy }));
}

export function emptyState(title, copy, actionLabel = null, action = null) {
	return el(
		"section",
		{ className: "full-state" },
		el("span", { className: "state-mark", text: "B_" }),
		el("h1", { text: title }),
		el("p", { text: copy }),
		action ? actionButton(actionLabel, action, {}, "button") : null,
	);
}

export function unavailableState() {
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

export function railSkeleton() {
	return el(
		"div",
		{ className: "rail-skeleton", attrs: { "aria-label": "Loading sessions" } },
		...Array.from({ length: 5 }, (_, index) => el("span", { className: `loading-line${index % 2 ? " short" : ""}` })),
	);
}

export function workspaceSkeleton() {
	return el(
		"div",
		{ className: "loading-state", attrs: { "aria-label": "Loading session detail" } },
		el("span", { className: "loading-line wide" }),
		el("span", { className: "loading-line" }),
		el("span", { className: "loading-block" }),
	);
}
