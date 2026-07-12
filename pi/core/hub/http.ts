import * as http from "node:http";

export interface HealthPingOk {
	ok: true;
	protocol: number;
}

export interface HealthPingFail {
	ok: false;
}

export type HealthPingResult = HealthPingOk | HealthPingFail;

export const DEFAULT_HEALTH_TIMEOUT_MS = 400;

export async function requestJsonOverUds(socketPath: string, path: string, timeoutMs: number): Promise<unknown | null> {
	return await new Promise((resolve) => {
		const req = http.request(
			{
				socketPath,
				path,
				method: "GET",
				timeout: timeoutMs,
			},
			(res) => {
				let body = "";
				res.setEncoding("utf8");
				res.on("data", (chunk) => {
					body += chunk;
				});
				res.on("end", () => {
					if (res.statusCode !== 200) {
						resolve(null);
						return;
					}
					try {
						resolve(JSON.parse(body) as unknown);
					} catch {
						resolve(null);
					}
				});
			},
		);
		req.on("timeout", () => {
			req.destroy();
			resolve(null);
		});
		req.on("error", () => {
			resolve(null);
		});
		req.end();
	});
}

export async function healthPing(socketPath: string, timeoutMs: number): Promise<HealthPingResult> {
	const parsed = await requestJsonOverUds(socketPath, "/health", timeoutMs);
	if (
		parsed &&
		typeof parsed === "object" &&
		(parsed as { status?: unknown }).status === "ok" &&
		typeof (parsed as { protocol?: unknown }).protocol === "number"
	) {
		return { ok: true, protocol: (parsed as { protocol: number }).protocol };
	}
	return { ok: false };
}

export function optionalString(value: unknown): string | null {
	return typeof value === "string" ? value : null;
}

export function optionalNumber(value: unknown): number | null {
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function optionalBoolean(value: unknown): boolean | null {
	return typeof value === "boolean" ? value : null;
}
