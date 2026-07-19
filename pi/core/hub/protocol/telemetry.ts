import type { ProtocolEnvelope } from "./version.ts";

export interface TelemetryFrame extends ProtocolEnvelope {
	type: "telemetry";
	run_id: string;
	agent_id: string;
	report_token: string;
	kind: string;
	payload: Record<string, unknown>;
}

export interface ResultReportFrame extends ProtocolEnvelope {
	type: "result_report";
	run_id: string;
	agent_id: string;
	report_token: string;
	status: "ok" | "error";
	result: string | null;
	error: string | null;
	usage: Record<string, unknown> | null;
}
