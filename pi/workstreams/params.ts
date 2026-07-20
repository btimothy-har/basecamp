import { isRecord } from "#core/host/files.ts";

export interface CreateWorkstreamParams {
	source: {
		dossierPath: string;
		repoPagePath?: string;
	};
	workstream: {
		label: string;
		brief: string;
		constraints?: string;
	};
}

export interface EditWorkstreamParams {
	workstream: string;
	label?: string;
	brief?: string;
	constraints?: string;
}

export interface LaunchWorkstreamParams {
	workstream: string;
	worktreeSlug?: string;
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

function optionalTrimmedString(value: unknown): string | undefined {
	if (value === undefined) return undefined;
	if (typeof value !== "string") return undefined;
	const trimmed = value.trim();
	return trimmed ? trimmed : undefined;
}

function requiredTrimmedString(
	value: unknown,
	path: string,
	tool: string,
): { ok: true; value: string } | { ok: false; message: string } {
	if (typeof value !== "string" || !value.trim()) {
		return { ok: false, message: `${tool} requires a non-empty ${path}.` };
	}
	return { ok: true, value: value.trim() };
}

export function parseCreateWorkstreamParams(
	params: unknown,
): { ok: true; value: CreateWorkstreamParams } | { ok: false; message: string } {
	if (!isRecord(params) || !isRecord(params.source) || !isRecord(params.workstream)) {
		return { ok: false, message: "create_workstream requires source and workstream objects." };
	}

	const dossierPath = requiredTrimmedString(params.source.dossierPath, "source.dossierPath", "create_workstream");
	if (!dossierPath.ok) return dossierPath;
	const label = requiredTrimmedString(params.workstream.label, "workstream.label", "create_workstream");
	if (!label.ok) return label;
	const brief = requiredTrimmedString(params.workstream.brief, "workstream.brief", "create_workstream");
	if (!brief.ok) return brief;

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
			},
		},
	};
}

export function parseEditWorkstreamParams(
	params: unknown,
): { ok: true; value: EditWorkstreamParams } | { ok: false; message: string } {
	if (!isRecord(params)) return { ok: false, message: "edit_workstream requires a workstream id or slug." };
	const workstream = requiredTrimmedString(params.workstream, "workstream", "edit_workstream");
	if (!workstream.ok) return workstream;

	const label = optionalTrimmedString(params.label);
	const brief = optionalTrimmedString(params.brief);
	const constraints = optionalTrimmedString(params.constraints);
	if (label === undefined && brief === undefined && constraints === undefined) {
		return {
			ok: false,
			message: "edit_workstream requires at least one of label, brief, or constraints to change.",
		};
	}

	return {
		ok: true,
		value: {
			workstream: workstream.value,
			...(label !== undefined ? { label } : {}),
			...(brief !== undefined ? { brief } : {}),
			...(constraints !== undefined ? { constraints } : {}),
		},
	};
}

export function parseLaunchWorkstreamParams(
	params: unknown,
): { ok: true; value: LaunchWorkstreamParams } | { ok: false; message: string } {
	if (!isRecord(params)) return { ok: false, message: "launch_workstream requires a workstream id or slug." };
	const workstream = requiredTrimmedString(params.workstream, "workstream", "launch_workstream");
	if (!workstream.ok) return workstream;

	const worktreeSlug = optionalTrimmedString(params.worktreeSlug);
	return {
		ok: true,
		value: {
			workstream: workstream.value,
			...(worktreeSlug ? { worktreeSlug } : {}),
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
