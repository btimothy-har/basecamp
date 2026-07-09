export interface LaunchWorkstreamParams {
	source: {
		dossierPath: string;
		repoPagePath?: string;
	};
	workstream: {
		label: string;
		brief: string;
		constraints?: string;
		worktreeSlug?: string;
	};
	workstreamId?: string;
}

export interface ListWorkstreamsParams {
	repo?: string;
	dossierPath?: string;
	query?: string;
	status?: "open" | "closed";
}

export interface SetWorkstreamStatusParams {
	workstream: string;
	status: "open" | "closed";
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalTrimmedString(value: unknown): string | undefined {
	if (value === undefined) return undefined;
	if (typeof value !== "string") return undefined;
	const trimmed = value.trim();
	return trimmed ? trimmed : undefined;
}

function requiredTrimmedString(
	value: unknown,
	path: string,
	tool = "launch_workstream",
): { ok: true; value: string } | { ok: false; message: string } {
	if (typeof value !== "string" || !value.trim()) {
		return { ok: false, message: `${tool} requires a non-empty ${path}.` };
	}
	return { ok: true, value: value.trim() };
}

export function parseLaunchWorkstreamParams(
	params: unknown,
): { ok: true; value: LaunchWorkstreamParams } | { ok: false; message: string } {
	if (!isRecord(params) || !isRecord(params.source) || !isRecord(params.workstream)) {
		return { ok: false, message: "launch_workstream requires source and workstream objects." };
	}

	const dossierPath = requiredTrimmedString(params.source.dossierPath, "source.dossierPath");
	if (!dossierPath.ok) return dossierPath;
	const label = requiredTrimmedString(params.workstream.label, "workstream.label");
	if (!label.ok) return label;
	const brief = requiredTrimmedString(params.workstream.brief, "workstream.brief");
	if (!brief.ok) return brief;
	const carryIdentifier = optionalTrimmedString(params.workstream_id);

	return {
		ok: true,
		value: {
			source: {
				dossierPath: dossierPath.value,
				...(optionalTrimmedString(params.source.repoPagePath)
					? { repoPagePath: optionalTrimmedString(params.source.repoPagePath) }
					: {}),
			},
			workstream: {
				label: label.value,
				brief: brief.value,
				...(optionalTrimmedString(params.workstream.constraints)
					? { constraints: optionalTrimmedString(params.workstream.constraints) }
					: {}),
				...(optionalTrimmedString(params.workstream.worktreeSlug)
					? { worktreeSlug: optionalTrimmedString(params.workstream.worktreeSlug) }
					: {}),
			},
			...(carryIdentifier ? { workstreamId: carryIdentifier } : {}),
		},
	};
}

export function parseListWorkstreamsParams(params: unknown): ListWorkstreamsParams {
	if (!isRecord(params)) return {};
	const query =
		optionalTrimmedString(params.query) ?? optionalTrimmedString(params.slug) ?? optionalTrimmedString(params.label);
	return {
		...(optionalTrimmedString(params.repo) ? { repo: optionalTrimmedString(params.repo) } : {}),
		...(optionalTrimmedString(params.dossierPath) ? { dossierPath: optionalTrimmedString(params.dossierPath) } : {}),
		...(query ? { query } : {}),
		...(params.status === "open" || params.status === "closed" ? { status: params.status } : {}),
	};
}

export function parseSetWorkstreamStatusParams(
	params: unknown,
): { ok: true; value: SetWorkstreamStatusParams } | { ok: false; message: string } {
	if (!isRecord(params)) return { ok: false, message: "set_workstream_status requires workstream and status." };
	const workstream = requiredTrimmedString(params.workstream, "workstream", "set_workstream_status");
	if (!workstream.ok) return workstream;
	const status = params.status;
	if (status !== "open" && status !== "closed") {
		return { ok: false, message: "set_workstream_status requires status to be 'open' or 'closed'." };
	}
	return { ok: true, value: { workstream: workstream.value, status } };
}
