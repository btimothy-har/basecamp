import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

type DaemonStatusKind = "idle" | "starting" | "connected" | "unavailable" | "disconnected";

export interface DaemonStatusInfo {
	kind: DaemonStatusKind;
	message?: string;
}

const DAEMON_STATUS_ID = "basecamp.daemon";
const DAEMON_MESSAGE_TRUNCATE_LENGTH = 80;

export function previewDaemonMessage(message: string | undefined): string | null {
	const sanitized = message?.replace(/[\r\n\t]/g, " ").trim();
	if (!sanitized) return null;
	if (sanitized.length <= DAEMON_MESSAGE_TRUNCATE_LENGTH) return sanitized;
	return `${sanitized.slice(0, DAEMON_MESSAGE_TRUNCATE_LENGTH - 1)}…`;
}

export function renderDaemonStatus(fg: ThemeFg, status: DaemonStatusInfo): string {
	if (status.kind === "connected") return fg("success", "swarm ✓");
	if (status.kind === "starting") return `${fg("warning", "swarm …")} ${fg("dim", "starting")}`;
	if (status.kind === "disconnected") return `${fg("warning", "swarm ⚠")} ${fg("dim", "disconnected")}`;
	if (status.kind === "unavailable") {
		const message = previewDaemonMessage(status.message);
		return message ? `${fg("error", "swarm ✗")} ${fg("error", message)}` : fg("error", "swarm ✗ unavailable");
	}
	return fg("muted", "swarm idle");
}

export function publishDaemonStatus(ctx: ExtensionContext, status: DaemonStatusInfo): void {
	if (!ctx.hasUI) return;
	const fg: ThemeFg = (color, text) => ctx.ui.theme.fg(color, text);
	ctx.ui.setStatus(DAEMON_STATUS_ID, renderDaemonStatus(fg, status));
}
