import type { PROTOCOL_VERSION } from "./version.ts";

export interface TelemetryFrame {
	type: "telemetry";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id: string;
	report_token: string;
	kind: string;
	payload: Record<string, unknown>;
}

export interface ResultReportFrame {
	type: "result_report";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id: string;
	report_token: string;
	status: "ok" | "error";
	result: string | null;
	error: string | null;
	usage: Record<string, unknown> | null;
}
